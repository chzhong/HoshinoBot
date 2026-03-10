from mmap import ACCESS_COPY
from msgpack import packb, unpackb
from hoshino.aiorequests import post
from random import randint
from json import loads
from hashlib import md5
from Crypto.Cipher import AES
from base64 import b64encode, b64decode
from asyncio import sleep
from re import search
from datetime import datetime
from dateutil.parser import parse

apiroot = 'https://l3-prod-uo-gs-gzlj.bilibiligame.net'

defaultHeaders = {
        'Expect': '100-continue',
        'EXCEL-VER': '1.0.0',
        'PARAM': 'f04cd44eebed9cfd4605ba0ff730d081f985a867',
        'KEYCHAIN': '',
        'SHORT-UDID': '1002298432',
        'CHANNEL-ID': '65',
        'MANIFEST-VER': '',
        'BATTLE-LOGIC-VERSION': '4',
        'REGION-CODE': 'CN',
        'PLATFORM-ID': '4',
        'PLATFORM': '2',
        'IP-ADDRESS': '',
        'DEVICE-ID': '',
        'LOCALE': 'Jpn',
        'PLATFORM-OS-VERSION': 'Android OS 6.0.1 / API-23 (V417IR/eng.duanlusheng.20220729.174739)',
        'X-Unity-Version': '2018.4.30f1',
        'DEVICE-NAME': 'Netease MuMu',
        'Content-Type': 'application/octet-stream',
        'GRAPHICS-DEVICE-NAME': 'Adreno (TM) 640',
        'BUNDLE-VER': '',
        'SID': '564fd204ec7d8f93c7530f3203f0f595',
        'APP-VER': '19.19.19',
        'RES-KEY': 'd145b29050641dac2f8b19df0afe0e59',
        'DEVICE': '2',
        'RES-VER': '10002200',
        'Content-Length': '70',
        'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 6.0.1; MuMu Build/V417IR)',
        'Host': 'l3-prod-uo-gs-gzlj.bilibiligame.net',
        'Connection': 'Keep-Alive',
        'Accept-Encoding': 'gzip'
        }

account_info = {
        "uid": "2021122022383802200000",
        "access_key": "d10137fa112c5430a6a19ce82cb8abe6",
        "platform": 4,
        "channel": 65
        }

AES_IV = b'7Fk9Lm3Np8Qr4Sv2'

class ApiException(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class pcrclient:
    def __init__(self):
        self.viewer_id = 0

        self.headers = {}
        for key in defaultHeaders.keys():
            self.headers[key] = defaultHeaders[key]
        self.uid = account_info["uid"]
        self.access_key = account_info["access_key"]
        self.platform = account_info["platform"]
        self.channel = account_info["channel"]
        self.shouldLogin = True

    
    @staticmethod
    def createkey() -> bytes:
        return bytes([ord('0123456789abcdef'[randint(0, 15)]) for _ in range(32)])
    
    @staticmethod
    def add_to_16(b: bytes) -> bytes:
        n = len(b) % 16
        n = n // 16 * 16 - n + 16
        return b + (n * bytes([n]))

    @staticmethod
    def pack(data: object, key: bytes) -> bytes:
        aes = AES.new(key, AES.MODE_CBC, AES_IV)
        return aes.encrypt(pcrclient.add_to_16(packb(data,
            use_bin_type = False
        ))) + key

    @staticmethod
    def encrypt(data: str, key: bytes) -> bytes:
        aes = AES.new(key, AES.MODE_CBC, AES_IV)
        return aes.encrypt(pcrclient.add_to_16(data.encode('utf8'))) + key

    @staticmethod
    def decrypt(data: bytes):
        data = b64decode(data.decode('utf8'))
        aes = AES.new(data[-32:], AES.MODE_CBC, AES_IV)
        return aes.decrypt(data[:-32]), data[-32:]

    @staticmethod
    def unpack(data: bytes):
        data = b64decode(data.decode('utf8'))
        aes = AES.new(data[-32:], AES.MODE_CBC, AES_IV)
        dec = aes.decrypt(data[:-32])
        return unpackb(dec[:-dec[-1]],
            strict_map_key = False
        ), data[-32:]

    async def callapi(self, apiurl: str, request: dict, crypted: bool = True, noerr: bool = False):
        key = pcrclient.createkey()

        try:    
            if self.viewer_id is not None:
                request['viewer_id'] = b64encode(pcrclient.encrypt(str(self.viewer_id), key)) if crypted else str(self.viewer_id)

            response = await (await post(apiroot + apiurl,
                data = pcrclient.pack(request, key) if crypted else str(request).encode('utf8'),
                headers = self.headers,
                timeout = 10)).content
            # print(apiurl, response)
            if len(response) == 0:
                return
            response = pcrclient.unpack(response)[0] if crypted else loads(response)

            data_headers = response['data_headers']

            if 'sid' in data_headers and data_headers["sid"] != '':
                t = md5()
                t.update((data_headers['sid'] + 'c!SID!n').encode('utf8'))
                self.headers['SID'] = t.hexdigest()
            
            if 'request_id' in data_headers:
                self.headers['REQUEST-ID'] = data_headers['request_id']

            if 'viewer_id' in data_headers:
                self.viewer_id = data_headers['viewer_id']
        
            data = response['data']
            if not noerr and 'server_error' in data:
                data = data['server_error']
                print(f'pcrclient: {apiurl} api failed {data}')
                raise ApiException(data['message'], data['status'])

            return data
        except:
            self.shouldLogin = True
            raise
    
    async def login(self):
        
        if 'REQUEST-ID' in self.headers:
            self.headers.pop('REQUEST-ID')

        while True:
            manifest = await self.callapi('/source_ini/get_maintenance_status?format=json', {}, False, noerr = True)
            if 'maintenance_message' not in manifest:
                break

            try:
                match = search('\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d', manifest['maintenance_message']).group()
                end = parse(match)
                print(f'server is in maintenance until {match}')
                while datetime.now() < end:
                    await sleep(1)
            except:
                print(f'server is in maintenance. waiting for 60 secs')
                await sleep(60)

        ver = manifest['required_manifest_ver']
        # print(f'using manifest ver = {ver}')
        self.headers['MANIFEST-VER'] = str(ver)
        lres = await self.callapi('/tool/sdk_login', {
            'uid': str(self.uid),
            'access_key': self.access_key,
            'channel': str(self.channel),
            'platform': str(self.platform)
        })
        
        gamestart = await self.callapi('/check/game_start', {
            'apptype': 0,
            'campaign_data': '',
            'campaign_user': randint(0, 99999)
        })

        if not gamestart['now_tutorial']:
            raise Exception("该账号没过完教程!")
            
        # await self.callapi('/check/check_agreement', {})

        await self.callapi('/load/index', {
            'carrier': 'OPPO'
        })
        await self.callapi('/home/index', {
            'message_id': 1,
            'tips_id_list': [],
            'is_first': 1,
            'gold_history': 0
        })

        self.shouldLogin = False


