import asyncio
import datetime
import enum
import io
import json
import random
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image
from loguru import logger
from sqlalchemy import select, func
from TiShiNengError import TiShiNengError
from TiShiNengRunPathManage import genTiShiNengRunPathRepeat
from database import get_db
from models import TsnAccount_Model, RunPath
from services.tsnAccount.tsnAccountDao import getTsnAccountByid
from tsnClient import getTsnClientById
import tsn_environment
import tsn_face_schedule
import tsn_payload

class TsnRunType(enum.Enum):
    morningRun = 1
    sumRun = 2
    freedom = 3

def seconds_to_time_format(total_seconds):
    hours = total_seconds // 3600
    minutes = total_seconds % 3600 // 60
    seconds = total_seconds % 60
    time_formatted = '{:02d}:{:02d}:{:02d}'.format(hours, minutes, seconds)
    return time_formatted

class TsnRunServer:

    def __init__(self, accountId: int, runKiloMeter: float, logRunType: TsnRunType):
        self.accountId = accountId
        self.runKiloMeter = runKiloMeter
        self.logRunType = logRunType
        self.accountModel: TsnAccount_Model | None = None
        self.tsnClient = None
        self.identify = None
        self.start_timestamp = None
        self.exerciseSetting = None
        self.geofence = None
        self.endStride = None
        self.limitSpeed = None
        self.endLimitStepFrequency = None
        self.pointList = None
        self.isMongoPath = True
        self.isPublic = False
        self.isFaceStatus = 1
        self.planUseTime = None
        self.needRunKm = None
        self.isStartFace = 0
        self.isEndFace = 0
        self.isMidwayFace = 0
        self.middleFaces = []
        self.startLongitude = 0
        self.startLatitude = 0

    @classmethod
    def publicRunTypeConvert(cls, runType: TsnRunType):
        if runType == TsnRunType.morningRun:
            return 2
        elif runType == TsnRunType.sumRun:
            return 1
        elif runType == TsnRunType.freedom:
            return 0
        else:
            raise ValueError('runType error')

    @staticmethod
    def _randomize_coordinates(longitude, latitude):
        random_longitude = random.uniform(longitude - 0.0005, longitude + 0.0005)
        random_latitude = random.uniform(latitude - 0.0005, latitude + 0.0005)
        return (random_longitude, random_latitude)

    @staticmethod
    def _validate_face_image(image_bytes: bytes) -> None:
        if not image_bytes:
            raise ValueError('图片内容为空')
        if len(image_bytes) > 10 * 1024 * 1024:
            raise ValueError('图片超过 10MB 限制')
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()

    @classmethod
    def _read_face_image(cls, path: Path) -> bytes:
        image_bytes = path.read_bytes()
        cls._validate_face_image(image_bytes)
        return image_bytes

    @staticmethod
    def _normalize_face_list(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ('records', 'list', 'rows', 'data'):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    async def getFaceImage(self, force_refresh=False):
        face_dir = Path('face_images') / str(self.accountModel.school_id) / str(self.accountModel.user_id)
        face_dir.mkdir(parents=True, exist_ok=True)
        existing_images = list(face_dir.glob('*.jpg')) + list(face_dir.glob('*.png'))
        if existing_images and not force_refresh:
            for selected_image in random.sample(existing_images, len(existing_images)):
                try:
                    logger.info(f'使用本地人脸图片: {selected_image}')
                    return self._read_face_image(selected_image)
                except (OSError, ValueError) as exc:
                    logger.warning(f'忽略无效的人脸缓存 {selected_image.name}: {exc}')
        logger.info('本地没有人脸图片，从服务器获取...')
        face_list_resp = await self.tsnClient.listBasUserImageFace()
        if face_list_resp is None:
            raise TiShiNengError('获取人脸列表失败，请检查网络连接或账号状态', 20001)
        face_data = self._normalize_face_list(face_list_resp)
        logger.info(f'底库返回 {len(face_data)} 条人脸图片记录')
        if not face_data:
            raise TiShiNengError('该账号没有人脸图片记录，请先在APP中上传人脸照片', 20002)
        download_count = 0
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, trust_env=False) as client:
            for idx, face_item in enumerate(face_data):
                image_url = face_item.get('imageRouteUrl')
                if not image_url:
                    continue
                try:
                    parsed_url = urlparse(image_url)
                    if parsed_url.scheme not in ('http', 'https') or not parsed_url.hostname:
                        raise ValueError('服务端返回了无效的图片地址')
                    logger.info(f'下载人脸图片 {idx + 1}/{len(face_data)}（来源: {parsed_url.hostname}）')
                    resp = await client.get(image_url)
                    if resp.status_code == 200:
                        self._validate_face_image(resp.content)
                        image_id = face_item.get('id', f'face_{idx}')
                        content_type = resp.headers.get('content-type', '').lower()
                        ext = '.png' if 'png' in content_type else '.jpg'
                        file_path = face_dir / f'{image_id}{ext}'
                        temp_path = file_path.with_suffix(file_path.suffix + '.tmp')
                        temp_path.write_bytes(resp.content)
                        temp_path.replace(file_path)
                        logger.info(f'人脸图片已保存: {file_path}')
                        download_count += 1
                    else:
                        logger.warning(f'下载失败，状态码: {resp.status_code}')
                except Exception as e:
                    logger.error(f'下载人脸图片失败: {e}')
                    continue
        existing_images = list(face_dir.glob('*.jpg')) + list(face_dir.glob('*.png'))
        if existing_images:
            selected_image = random.choice(existing_images)
            logger.info(f'使用刚下载的人脸图片: {selected_image} (共下载 {download_count} 张)')
            with open(selected_image, 'rb') as f:
                return f.read()
        else:
            raise TiShiNengError(f'人脸图片下载失败，尝试下载 {len(face_data)} 张但都失败了，请检查网络连接', 20003)

    async def uploadFace(self, coordinates, sleep=0, faceType=1):
        if not self.isPublic:
            return
        if sleep > 0:
            await asyncio.sleep(sleep)
        face_image = await self.getFaceImage()

        await self.tsnClient.exerciseRunningFace(face_image, coordinates, self.identify, self.publicRunTypeConvert(self.logRunType), faceType)

    async def queryPath(self):
        resultStmt = select(RunPath).where(RunPath.school_code == self.tsnClient.schoolCode).order_by(func.abs(RunPath.sport_range - self.runKiloMeter)).limit(10)
        async for newDb in get_db():
            result = await newDb.execute(resultStmt)
            runPathList = result.scalars().all()
            if len(runPathList) == 0:
                raise TiShiNengError('没有可用的跑步路线', 200000)
            runPath = random.choice(runPathList)
            result = {'runLinePath': json.loads(runPath.run_line_path)}
            runLinePath = result['runLinePath']
            return runLinePath
        return None

    def getOkPointList(self, startTime, endTime):
        okPointList = []
        timeStep = (endTime - startTime) // (len(self.pointList) + 4)
        timeStamp = startTime + timeStep
        for i in self.pointList:
            dt_object = datetime.datetime.fromtimestamp(timeStamp / 1000)
            formatted_string = dt_object.strftime('%Y-%m-%d %H:%M:%S')
            tmp = {'latitude': float(i['latitude']), 'content': i['content'], 'id': i['id'], 'time': formatted_string, 'longitude': float(i['longitude'])}
            if 'sort' in i:
                tmp['sort'] = i['sort']
            okPointList.append(tmp)
            timeStamp += timeStep
        return okPointList

    def _normalize_middle_faces(self):
        return tsn_face_schedule.normalize_middle_faces(self.middleFaces)

    def buildMiddleFacePoints(self, path, startTime, endTime):
        points = tsn_face_schedule.build_middle_face_points(path=path, start_timestamp_ms=int(startTime), end_timestamp_ms=int(endTime), middle_faces=self.middleFaces, is_public=bool(self.isPublic), face_type=2)
        result = [point.as_dict() for point in points]
        logger.info(f'中途人脸验证点: {result}')
        return result

    async def uploadRunPath(self, path, stepNumbers, sumDistance):
        sportRange = str(round(sumDistance / 1000, 2))
        gpsDistance = sportRange
        if self.isPublic:
            endTime = path[-1]['t']
        else:
            endTime = path[-1]['time']
        endTime += random.randint(100, 200)
        endTimeStr = datetime.datetime.fromtimestamp(endTime / 1000).strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f'跑步中，预计结束时间：{endTimeStr}')
        usedTime = (endTime - int(self.start_timestamp)) // 1000
        okPointList = self.getOkPointList(int(self.start_timestamp), endTime)
        distanceKm = sumDistance / 1000
        paceTime = usedTime / distanceKm
        paceMinute = int(paceTime // 60)
        paceSecond = int(paceTime % 60)
        pace = f'''{paceMinute}'{paceSecond}"'''
        logger.info(f'配速：{pace}')
        logger.info(f'usedTime:{usedTime}')
        sleepTime = int(endTime) / 1000 - time.time()
        taskList = []
        logger.info(f'等待{sleepTime}秒')
        taskList.append(asyncio.sleep(sleepTime))
        middleFacePoints = self.buildMiddleFacePoints(path, int(self.start_timestamp), endTime)
        for middleFaceItem in middleFacePoints:
            if sleepTime > 0:
                middleUsedTime = int(middleFaceItem['timestamp']) / 1000 - time.time()
                if middleUsedTime < 0:
                    middleUsedTime = 0
            else:
                middleUsedTime = 0
            latitude = middleFaceItem['latitude']
            longitude = middleFaceItem['longitude']
            coordinates = f'{latitude},{longitude}'
            taskList.append(self.uploadFace(coordinates=coordinates, sleep=middleUsedTime, faceType=2))
        await asyncio.gather(*taskList)
        avgSpeed = round(sumDistance / usedTime * 3.6, 2)
        if self.isEndFace == 1:
            logger.info('结束跑人脸识别')
            lastPoint = path[-1]
            if self.isPublic:
                lat = lastPoint['a']
                lng = lastPoint['o']
            else:
                lat = lastPoint['latitude']
                lng = lastPoint['longitude']
            coordinates = f'{lat},{lng}'
            await self.uploadFace(coordinates=coordinates, sleep=0, faceType=3)
        pointList = self.pointList.copy()
        for point in pointList:
            if 'isMustPoint' in point:
                point['isMustPoint'] = float(point['isMustPoint'])
            if 'okRadius' in point:
                point['okRadius'] = float(point['okRadius'])
        logger.info('上传跑步数据')
        for item in path:
            item.pop('distance', None)
        if self.isPublic:
            total_steps = sum((int(n) for n in stepNumbers))
            setting = self.exerciseSetting or {}
            submit_extras = tsn_payload.build_submit_extras(setting=setting, points=path, elapsed_s=usedTime, distance_m=sumDistance, steps=total_steps, user_open_develop=setting.get('userOpenDevelop', False), offline=0)
            logger.info(f'2.0.23 提交字段: {submit_extras}')
            logger.info(f'合格性判定明细: {tsn_payload.qualification_detail(setting, usedTime, sumDistance, total_steps)}')
            stopResp, exerciseRecordId = await self.tsnClient.addExerciseRecord(sportType=self.publicRunTypeConvert(self.logRunType), startTime=self.start_timestamp, endTime=endTime, sportTime=usedTime, sportRange=sportRange, speed=pace, avgSpeed=str(avgSpeed), gitudeLatitude=json.dumps(path), stepNumbers=json.dumps(stepNumbers), isSequencePoint='0', pointList=json.dumps(pointList, ensure_ascii=False), okPointList=json.dumps(okPointList, ensure_ascii=False), isFaceStatus=1, uploadType=0, identify=self.identify, geofence=json.dumps(self.geofence), limitSpeed=self.limitSpeed, limitStride=self.endStride, limitStepFrequency=self.endLimitStepFrequency, gpsDistance=gpsDistance, d=submit_extras.get('d'), f=submit_extras.get('f'), m=submit_extras.get('m'), h=submit_extras.get('h'), isValid=submit_extras.get('isValid'), remarkId=submit_extras.get('remarkId'), setting=setting, trackPoints=path, stepCount=total_steps, elapsedSeconds=usedTime, distanceMeters=sumDistance)
            await self.tsnClient.sumExerciseRecord()
            logger.info(stopResp)
            logger.info(exerciseRecordId)
            if exerciseRecordId is not None:
                exerciseRecordResp = await self.tsnClient.getExerciseRecord(exerciseRecordId)
                sportStatus = exerciseRecordResp['sportStatus']
                remark = exerciseRecordResp['remark']
                logger.info(remark)
                if str(sportStatus) != '1':
                    raise TiShiNengError(remark, 200000)
                await self.tsnClient.getFeedbackBalance()
                await self.tsnClient.sumExerciseRecord()
                await self.tsnClient.statisticsExerciseRecord()
        else:
            formatSportTime = seconds_to_time_format(usedTime)
            stopResp = await self.tsnClient.appAddSportRecord(runType=self.logRunType.value, startTime=self.start_timestamp, endTime=endTime, gitudeLatitude=json.dumps(path), identify=self.identify, formatSportTime=formatSportTime, formatSportRange=sportRange, avgspeed=str(avgSpeed), speed=pace, okPointList=json.dumps(okPointList), stepNumbers=json.dumps(stepNumbers), isFaceStatus=0, points=json.dumps(self.pointList), uploadType=0)
            logger.info(stopResp)
            sportRecord = await self.tsnClient.sumSportRecord()
            await asyncio.sleep(5)
            appSportRecordList = await self.tsnClient.appSportRecordList()
            appSportRecordListData = appSportRecordList['data'][0]
            if appSportRecordListData['sportStatus'] != 1:
                raise TiShiNengError(appSportRecordListData['remark'], 200000)
            logger.info('跑步数据上传完成')

    async def startRun(self):
        async for newDb in get_db():
            self.accountModel = await getTsnAccountByid(self.accountId, newDb)
            self.tsnClient = await getTsnClientById(self.accountModel.id, newDb)
        self.isPublic = self.tsnClient.isPublic()
        canRunTypeList = []
        if self.isPublic:
            initSumRunResp = await self.tsnClient.sumExerciseRecord()
            if initSumRunResp['morningRun']['isShow'] == '1':
                canRunTypeList.append(TsnRunType.morningRun)
            if initSumRunResp['sunRun']['isShow'] == '1':
                canRunTypeList.append(TsnRunType.sumRun)
            if initSumRunResp['freedomRun']['isShow'] == '1':
                canRunTypeList.append(TsnRunType.freedom)
        else:
            initSettingResp = await self.tsnClient.sportRecordSetting()
            freedom = initSettingResp['freedom']
            sunRun = initSettingResp['sunRun']
            morningRun = initSettingResp['morningRun']
            if freedom == 0:
                canRunTypeList.append(TsnRunType.freedom)
            if sunRun == 0:
                canRunTypeList.append(TsnRunType.sumRun)
            if morningRun == 0:
                canRunTypeList.append(TsnRunType.morningRun)
        if len(canRunTypeList) == 0:
            raise TiShiNengError('没有可用的跑步类型', 200000)
        logger.info(f'可用跑步类型：{canRunTypeList}')
        if self.logRunType not in canRunTypeList:
            raise TiShiNengError('当前跑步类型不可用', 200000)
        runLinePath = await self.queryPath()
        startPoint = runLinePath[0]
        logger.info(f'起点信息：{startPoint}')
        if self.isPublic:
            longitude = startPoint[0]
            latitude = startPoint[1]
            if longitude is not None and latitude is not None:
                longitude, latitude = self._randomize_coordinates(longitude, latitude)
            self.startLongitude = longitude
            self.startLatitude = latitude
            self.exerciseSetting = await self.tsnClient.getExerciseSetting(self.publicRunTypeConvert(self.logRunType), longitude, latitude)
            logger.info(f'school{self.tsnClient.schoolId} setting Info:{self.exerciseSetting}')
            await self.tsnClient.getExerciseExplanation()
        else:
            self.exerciseSetting = await self.tsnClient.getSportSetting(self.logRunType.value)
        if self.identify is None or self.start_timestamp is None:
            self.identify = self.exerciseSetting['identify']
            if self.isPublic:
                startTimeResp = await self.tsnClient.getExerciseStartTime(self.identify)
            else:
                startTimeResp = await self.tsnClient.getRunningStartTime(self.identify)
            self.start_timestamp = int(startTimeResp['startTime']) + random.randint(14, 20) * 1000
        self.isStartFace = int(self.exerciseSetting.get('isStartFace', 0))
        self.isEndFace = int(self.exerciseSetting.get('isEndFace', 0))
        self.middleFaces = self.exerciseSetting.get('middleFaces', [])
        self.isMidwayFace = int(self.exerciseSetting.get('isMidwayFace', 0))
        if len(self.middleFaces) == 0 and self.isMidwayFace == 1:
            self.middleFaces.append(random.uniform(0.5, 1.2))
        if not (len(self.middleFaces) > 0 or self.isStartFace == 1 or self.isEndFace == 1 or (self.isMidwayFace == 1)):
            self.isFaceStatus = 0
        if hasattr(self.tsnClient, 'setEnvSignals'):
            self.tsnClient.setEnvSignals(tsn_environment.clean_device_signals())
        if self.isStartFace == 1:
            logger.info('开始人脸识别')
            coordinates = f'{self.startLatitude},{self.startLongitude}'
            await asyncio.sleep(random.uniform(7, 12))
            await self.uploadFace(coordinates=coordinates, faceType=1)
        self.geofence = self.exerciseSetting['geofence']
        self.pointList = self.exerciseSetting.get('list', [])
        if self.pointList == '':
            self.pointList = []
        if 'campusList' in self.exerciseSetting:
            campusList = self.exerciseSetting['campusList']
            campusIdPointDict = {}
            for campus in campusList:
                campusIdPointDict[campus['id']] = campus['point']
            userInfo = await self.tsnClient.getLoginUserInfo()
            campusId = userInfo['campusId']
            if campusId in campusIdPointDict:
                self.pointList = campusIdPointDict[campusId]
            else:
                self.pointList = campusIdPointDict[random.choice(list(campusIdPointDict.keys()))]
        logger.info(f'pointList:{self.pointList}')
        self.needRunKm = self.exerciseSetting['totalRange']
        if self.runKiloMeter < self.needRunKm:
            self.runKiloMeter = self.needRunKm + random.uniform(0.1, 0.2)
        logger.info(self.exerciseSetting)
        self.planUseTime = self.runKiloMeter * random.uniform(4.5, 5.5) * 60
        logger.info(f'planUseTime:{self.planUseTime}')
        if self.isPublic:
            self.endStride = self.exerciseSetting['endStride']
            self.limitSpeed = self.exerciseSetting['limitSpeed']
            self.endLimitStepFrequency = self.exerciseSetting['endLimitStepFrequency']
        await asyncio.sleep(random.uniform(1, 4))
        geoData, stepList, sumDistance = genTiShiNengRunPathRepeat(runLinePath, self.runKiloMeter * 1000, int(self.start_timestamp) + random.randint(1200, 1800), self.planUseTime, self.isPublic)
        await self.uploadRunPath(geoData, stepList, sumDistance)

    async def startRunHandle(self):
        logger.info('开始运行')
        await self.startRun()
