#!/bin/bash
# no outbound network: container on an --internal network serves UI + assets, and cannot reach the internet
service docker start >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do docker info >/dev/null 2>&1 && break; sleep 1; done
docker rm -f pf-internal-run >/dev/null 2>&1
docker network rm pf-internal >/dev/null 2>&1
docker network create --internal pf-internal >/dev/null
docker run -d --name pf-internal-run --network pf-internal ${S3IMG:-pocketful-s3} >/dev/null
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' pf-internal-run)
echo "container ip $IP"
sleep 1
docker run --rm --network pf-internal -e IP="$IP" --entrypoint python3 df-harness-runner:latest -c "
import os, urllib.request
ip=os.environ['IP']
for p in ['/health','/','/assets/js/main.js','/assets/css/tokens.css','/assets/fonts/dm-sans.woff2','/assets/fonts/inter.woff2']:
    r=urllib.request.urlopen('http://%s:8080%s'%(ip,p)); print(p, r.status, r.headers.get('Content-Type'), len(r.read()))
try:
    urllib.request.urlopen('http://1.1.1.1', timeout=3); print('OUTBOUND REACHABLE (unexpected)')
except Exception as e: print('outbound blocked:', type(e).__name__)
"
docker rm -f pf-internal-run >/dev/null 2>&1
docker network rm pf-internal >/dev/null 2>&1
