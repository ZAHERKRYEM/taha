
#!/usr/bin/env bash
# أمر البناء على Render:  ./build.sh
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py createcachetable
