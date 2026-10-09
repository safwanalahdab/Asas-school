# Production Redis and Nginx

This deployment assumes exactly one trusted Nginx proxy between clients and
Gunicorn/Django. `NUM_PROXIES = 1` must be reviewed before adding Cloudflare,
a load balancer, or another proxy.

## Redis

Install Redis and keep it bound to localhost only. Do not expose port 6379 to
the public internet. Add this to the backend process environment:

```text
REDIS_URL=redis://127.0.0.1:6379/1
DJANGO_SETTINGS_MODULE=config.production_settings
```

Check the service locally, then restart Gunicorn:

```bash
sudo systemctl status redis-server
redis-cli -h 127.0.0.1 ping
sudo systemctl restart gunicorn
```

## Nginx

Nginx must replace client-supplied forwarding headers:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
```

After deployment, make repeated invalid Web and Mobile Login requests from a
controlled client and confirm the existing limit returns HTTP 429 on the sixth
request within one minute. Also confirm multiple Gunicorn workers share the
same count.
