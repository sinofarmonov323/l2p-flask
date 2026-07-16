# ltp - Local to Public

## Installation
```
pip install local2public
```

## Usage
```
ltp --port [port_number] --name [your_website_name]
```

The public URL is generated as a subdomain:
```
https://[your_website_name].myurl.com/
```

For deployment, point `*.myurl.com` to the server and set:
```
LTP_BASE_DOMAIN=myurl.com
```

For the CLI, set:
```
LTP_SERVER_URL=http://myurl.com
LTP_PUBLIC_BASE_URL=https://myurl.com
```

## Production notes
For Azure with Caddy:

- Create DNS records for both `myurl.com` and `*.myurl.com` pointing to the Azure public IP.
- Open ports `80` and `443` in the Azure network security group so Caddy can issue and renew certificates.
- Run the Flask app behind Caddy (with gunicorn), for example on `127.0.0.1:8000`.
- Use the included `Caddyfile.example` as the starting reverse proxy config.
- Keep Flask docs disabled in production.

Recommended server environment:
```
LTP_BASE_DOMAIN=myurl.com
LTP_REQUEST_TIMEOUT=30
LTP_MAX_BODY_BYTES=10485760
PORT=8000
SECRET_KEY=your-secret-key-here
```

## Running the server
```
python app.py
```

Or with gunicorn (for production):
```
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8000 app:app
```

# O'zbekchada
## O'RNATISH
```
pip install local2public
```

## ISHLATISH
```
ltp --port [port_raqami] --name [websaytingizning_nomi]
```

URL subdomain orqali yaratiladi:
```
https://[websaytingizning_nomi].myurl.com/
```
