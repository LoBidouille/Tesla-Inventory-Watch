import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('app.main:create_app', factory=True, host=os.getenv('HOST', '127.0.0.1'),
                port=int(os.getenv('PORT', '8080')), workers=1, proxy_headers=True,
                forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1'))
