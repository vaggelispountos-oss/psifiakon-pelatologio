# backend/Dockerfile
# --------------------------------------------------------------------
# Production image του Flask backend. Αντικατοπτρίζει το render.yaml:
# ίδια εξάρτηση σε Postgres/Redis, ίδια gunicorn flags, ίδιο migration
# βήμα ΠΡΙΝ ξεκινήσουν οι workers (δες docker-compose.yml, service
# `migrate`).
# --------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# postgresql-client: για να τρέχουν τα scripts/backup_db.sh και
# scripts/restore_db.sh ΜΕΣΑ από το container (docker compose exec backend
# ...) χωρίς να χρειάζεται εγκατεστημένο Postgres στο host.
# curl: για το HEALTHCHECK παρακάτω.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ξεχωριστό COPY των requirements ΠΡΙΝ τον υπόλοιπο κώδικα: όσο δεν αλλάζουν
# οι εξαρτήσεις, το `pip install` layer έρχεται από cache και το rebuild μετά
# από αλλαγή κώδικα παίρνει δευτερόλεπτα αντί για λεπτά.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Μη-root χρήστης: αν ποτέ βρεθεί RCE σε endpoint, ο επιτιθέμενος δεν είναι
# root μέσα στο container. Το instance/ πρέπει να ανήκει σε αυτόν γιατί εκεί
# γράφει το Flask-SQLAlchemy όταν το DATABASE_URL είναι SQLite (τοπική
# δοκιμή χωρίς Postgres — δες config._normalize_db_url).
RUN useradd --create-home --uid 1000 appuser \
 && mkdir -p /app/instance \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:5001/api/health || exit 1

# Ίδια flags με το startCommand του render.yaml — δες ΕΚΕΙ τα σχόλια για το
# γιατί (--timeout 120 πρέπει να είναι > 60s worst-case ΑΑΔΕ· threads και όχι
# processes γιατί το bottleneck είναι αναμονή δικτύου προς ΑΑΔΕ, όχι CPU).
# --access-logfile/-error-logfile στο stdout/stderr ώστε να τα πιάνει το
# `docker compose logs`.
CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
