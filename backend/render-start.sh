#!/bin/sh
# Boot único do serviço no Render — free tier não tem Pre-Deploy Command
# nem Background Worker pagos, então o container web faz tudo:
#   1. collectstatic -> estáticos do admin (whitenoise), antes de servir
#   2. migrate       -> idempotente; só este dyno migra (o build não tem env)
#   3. settle loop   -> worker de liquidação em background (mesmo container;
#                       se morrer, o fallback lazy do detalhe cobre)
#   4. daphne        -> ASGI na porta do Render, com exec para receber signals
# O campo "Docker Command" do Render é executado SEM shell (exec direto),
# por isso o comando lá deve ser apenas: sh render-start.sh
set -e
python manage.py collectstatic --noinput
python manage.py migrate
python manage.py settle_auctions_loop --interval 5 &
exec daphne -b 0.0.0.0 -p "${PORT:-10000}" config.asgi:application
