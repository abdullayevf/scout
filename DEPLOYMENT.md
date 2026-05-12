# Deployment

## Requirements

- Linux server with Docker + Docker Compose installed
- Domain name with an A record pointing to the server
- SSL certificate — [Let's Encrypt](https://letsencrypt.org/) via `certbot` recommended

## First-time setup

```bash
git clone https://github.com/abdullayevf/scout.git
cd scout
cp .env.example .env
# Fill in every value — see Environment Variables in README.md
```

Get an SSL cert:

```bash
sudo certbot certonly --nginx -d <your-domain>
```

Add a system nginx virtual host using `infra/nginx.conf` as a template. Replace `${DOMAIN}` with your domain and update the proxy ports to match `BOT_HOST_PORT` and `API_HOST_PORT` from your `.env`.

Launch:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec worker alembic upgrade head
```

The bot sets its own Telegram webhook automatically on startup using `TELEGRAM_WEBHOOK_URL` from `.env`.

## Port conflicts

If other services already occupy the default ports on your host, override them in `.env`:

```env
BOT_HOST_PORT=127.0.0.1:8081    # default: 8080
API_HOST_PORT=127.0.0.1:8001    # default: 8000
POSTGRES_HOST_PORT=127.0.0.1:5439   # default: 5433
REDIS_HOST_PORT=127.0.0.1:6382      # default: 6380
```

## Subsequent deploys

```bash
./deploy.sh
```

`deploy.sh` runs: `git pull` → `docker compose build` → `docker compose up -d` → `alembic upgrade head`.
