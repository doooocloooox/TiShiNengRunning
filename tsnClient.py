import uuid
from loguru import logger
from TiShiNengError import TiShiNengError
from TiShiNengSdkPrivate import TiShiNengPrivate
from TiShiNengSdkPublic import TiShiNengSdkPublic
from database import get_db
from deviceModel import deviceModel
from models import TsnAccount_Model
from services.tsnAccount.tsnAccountDao import updateAccessToken, getTsnAccountByid, getTsnAccountByUid, addTsnAccount
from services.tsnSchool.tsnSchoolDao import getSchoolBySchoolId
from security import protect_secret, reveal_secret, safe_json

async def getPublicVersionClient(accountModel: TsnAccount_Model):
    schoolId = accountModel.school_id
    uid = accountModel.user_id
    schoolCode = accountModel.school.school_code
    openId = accountModel.school.open_id
    lan_url = accountModel.school.lan_url
    deviceId = accountModel.mobile_device_id
    brandName = deviceModel.brand
    deviceNum = deviceModel.model
    osVersion = deviceModel.osver
    a_list = deviceModel.a_list
    access_token = reveal_secret(accountModel.access_token)
    fresh_token = reveal_secret(accountModel.refresh_token)
    username = accountModel.username
    password = reveal_secret(accountModel.password)
    tsn = TiShiNengSdkPublic(uid, schoolId, schoolCode, openId, deviceId, brandName, deviceNum, osVersion, access_token, a_list)
    if lan_url != '' and lan_url is not None:
        tsn.setCloudUrl(lan_url)
    async def reauthenticate():
        token_resp = await tsn.getAccessToken(username, password)
        logger.debug('重新登录响应: {}', safe_json(token_resp))
        if not isinstance(token_resp, dict) or 'msg' in token_resp or not token_resp.get('access_token'):
            message = token_resp.get('msg', '账号密码重新授权失败') if isinstance(token_resp, dict) else '账号密码重新授权失败'
            raise TiShiNengError(message, 10001)
        async for newDb in get_db():
            await updateAccessToken(accountModel.id, newDb, token_resp['access_token'], token_resp['refresh_token'], token_resp['expires_in'])
        tsn.setToken(token_resp['access_token'])
    try:
        fresh_token_resp = await tsn.freshToken(fresh_token)
        refresh_ok = isinstance(fresh_token_resp, dict) and 'msg' not in fresh_token_resp and bool(fresh_token_resp.get('access_token'))
        if refresh_ok:
            async for newDb in get_db():
                await updateAccessToken(accountModel.id, newDb, fresh_token_resp['access_token'], fresh_token_resp['refresh_token'], fresh_token_resp['expires_in'])
            tsn.setToken(fresh_token_resp['access_token'])
        else:
            logger.info('刷新令牌已失效，使用账号密码重新授权')
            await reauthenticate()
    except TiShiNengError as e:
        if e.code == 401:
            logger.info('刷新令牌已失效，使用账号密码重新授权')
            await reauthenticate()
        else:
            raise e
    return tsn

async def getPrivateVersionClient(accountModel: TsnAccount_Model):
    schoolId = accountModel.school_id
    uid = accountModel.user_id
    schoolCode = accountModel.school.school_code
    openId = accountModel.school.open_id
    school_url = accountModel.school.school_url
    isOpenEncry = accountModel.school.is_open_encry
    deviceId = accountModel.mobile_device_id
    brandName = deviceModel.brand
    deviceNum = deviceModel.model
    access_token = reveal_secret(accountModel.access_token)
    username = accountModel.username
    password = reveal_secret(accountModel.password)
    tsn = TiShiNengPrivate(uid, schoolId, schoolCode, isOpenEncry, deviceId, brandName, deviceNum, access_token)
    tsn.setSchoolUrl(school_url)
    tsn.setAppId(openId)
    try:
        testTokenResp = await tsn.getStudentInfo()
        if testTokenResp is None:
            raise TiShiNengError('token失效', 401)
    except TiShiNengError as e:
        if e.code == 401 or e.message == '登录失效' or '学生信息系统不存在' in e.message:
            logger.info('token失效，重新获取')
            tokenResp = await tsn.appLogin(username, password)
            logger.debug('重新登录响应: {}', safe_json(tokenResp))
            async for newDb in get_db():
                await updateAccessToken(accountModel.id, newDb, tokenResp['token'], '2', 86399)
            tsn.setAccessToken(tokenResp['token'])
        else:
            raise e
    return tsn

async def getTsnClientById(accountId, session):
    account: TsnAccount_Model = await getTsnAccountByid(accountId, session)
    if account.school.sys_type == 2:
        return await getPublicVersionClient(account)
    elif account.school.sys_type == 1:
        return await getPrivateVersionClient(account)
    else:
        raise TiShiNengError('未知的系统类型', 10001)

async def getTsnClientByUid(uid, session):
    account: TsnAccount_Model = await getTsnAccountByUid(uid, session)
    if account.school.sys_type == 2:
        return await getPublicVersionClient(account)
    elif account.school.sys_type == 1:
        return await getPrivateVersionClient(account)
    else:
        raise TiShiNengError('未知的系统类型', 10001)

async def tsnPasswordAuthServer(schoolId, userName, password, session):
    schoolModel = await getSchoolBySchoolId(schoolId, session)
    if not schoolModel:
        raise TiShiNengError('学校不存在')
    brandName = deviceModel.brand
    deviceNum = deviceModel.model
    osVersion = deviceModel.osver
    a_list = deviceModel.a_list
    deviceId = str(uuid.uuid4())
    if schoolModel.isPublicVersion():
        tsn = TiShiNengSdkPublic(0, schoolId, schoolModel.school_code, schoolModel.open_id, deviceId, brandName, deviceNum, osVersion, '', a_list)
        if schoolModel.lan_url != '' and schoolModel.lan_url is not None:
            tsn.setCloudUrl(schoolModel.lan_url)
        loginResp = await tsn.getAccessToken(userName, password)
        logger.debug('登录响应: {}', safe_json(loginResp))
        if 'msg' in loginResp:
            if 'Bad credentials' in loginResp['msg']:
                raise TiShiNengError('用户名错误')
            elif 'Wrong password.' in loginResp['msg']:
                raise TiShiNengError('密码错误')
            raise TiShiNengError(loginResp['msg'])
        accessToken = loginResp['access_token']
        refreshToken = loginResp['refresh_token']
        expiresIn = loginResp['expires_in']
        uid = loginResp['user_id']
        del tsn
        tsn = TiShiNengSdkPublic(uid, schoolId, schoolModel.school_code, schoolModel.open_id, deviceId, brandName, deviceNum, osVersion, accessToken, a_list)
        if schoolModel.lan_url != '' and schoolModel.lan_url is not None:
            tsn.setCloudUrl(schoolModel.lan_url)
        userInfo = await tsn.getLoginUserInfo()
        logger.debug('用户信息响应: {}', safe_json(userInfo))
        tsnAccountModel = await getTsnAccountByUid(uid, session)
        saveFlag = False
        if not tsnAccountModel:
            tsnAccountModel = TsnAccount_Model()
            saveFlag = True
        tsnAccountModel.student_id = userInfo['studentId']
        tsnAccountModel.user_id = uid
        tsnAccountModel.school_id = schoolId
        tsnAccountModel.username = userName
        tsnAccountModel.password = protect_secret(password)
        tsnAccountModel.mobile_device_id = deviceId
        tsnAccountModel.access_token = protect_secret(accessToken)
        tsnAccountModel.refresh_token = protect_secret(refreshToken)
        tsnAccountModel.expires_in = expiresIn
        if saveFlag:
            await addTsnAccount(tsnAccountModel, session)
        else:
            await session.flush()
        return uid
    else:
        tsn = TiShiNengPrivate(0, schoolId, schoolModel.school_code, schoolModel.is_open_encry, deviceId, brandName, deviceNum, '')
        tsn.setAppId(schoolModel.open_id)
        tsn.setSchoolUrl(schoolModel.school_url)
        loginResp = await tsn.appLogin(userName, password)
        logger.debug('登录响应: {}', safe_json(loginResp))
        userNum = loginResp['userNum']
        uid = loginResp['id']
        token = loginResp['token']
        del tsn
        tsnAccountModel = await getTsnAccountByUid(uid, session, schoolId)
        saveFlag = False
        if not tsnAccountModel:
            tsnAccountModel = TsnAccount_Model()
            saveFlag = True
        tsnAccountModel.student_id = userNum
        tsnAccountModel.user_id = uid
        tsnAccountModel.school_id = schoolId
        tsnAccountModel.username = userName
        tsnAccountModel.password = protect_secret(password)
        tsnAccountModel.mobile_device_id = deviceId
        tsnAccountModel.access_token = protect_secret(token)
        tsnAccountModel.refresh_token = protect_secret('')
        tsnAccountModel.expires_in = 86399
        if saveFlag:
            await addTsnAccount(tsnAccountModel, session)
        else:
            await session.flush()
        sysUid = f'{schoolId}:{uid}'
        return sysUid
