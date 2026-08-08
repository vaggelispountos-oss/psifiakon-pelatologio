# frontend/Dockerfile
# --------------------------------------------------------------------
# Multi-stage: node χτίζει το Vite bundle, nginx το σερβίρει.
# Ο ρόλος του nginx εδώ είναι ο ίδιος με του Vercel σε production (static
# hosting + SPA rewrites + cache headers για τον service worker), με μία
# προσθήκη: κάνει proxy το /api στο backend, ώστε ο browser να βλέπει ΕΝΑ
# origin (δες nginx.conf).
# --------------------------------------------------------------------

# --- build stage ---
FROM node:22-alpine AS build

WORKDIR /app

# npm ci (όχι install): εγκαθιστά ΑΚΡΙΒΩΣ τις εκδόσεις του package-lock.json,
# οπότε το image είναι αναπαραγώγιμο. Ξεχωριστό layer από τον κώδικα για
# cache (ίδια λογική με το backend/Dockerfile).
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# ΠΡΟΣΟΧΗ — build-time, ΟΧΙ runtime: το Vite ενσωματώνει τις VITE_*
# μεταβλητές μέσα στο JS bundle την ώρα του build. Αλλαγή αυτής της τιμής
# ΑΠΑΙΤΕΙ rebuild του image (`docker compose build frontend`), δεν αρκεί
# restart του container.
#
# Κενό (default) = το frontend καλεί σχετικά /api/... που τα κάνει proxy το
# nginx στο backend — ΕΝΑ origin για τον browser, άρα μηδέν CORS. Όρισέ το
# ΜΟΝΟ αν βάλεις το backend σε ξεχωριστό domain (τότε ρύθμισε αντίστοιχα και
# το CORS_ORIGINS στο backend, αλλιώς ο browser θα μπλοκάρει τις κλήσεις).
ARG VITE_API_URL=""

# Γράφεται σε .env.production (το `vite build` τρέχει σε mode=production)
# αντί για σκέτο ENV: έτσι η τιμή περνά ΝΤΕΤΕΡΜΙΝΙΣΤΙΚΑ στο bundle, χωρίς να
# εξαρτιόμαστε από το αν το Vite διαβάζει process.env για VITE_* μεταβλητές.
RUN printf 'VITE_API_URL=%s\n' "$VITE_API_URL" > .env.production

RUN npm run build

# --- runtime stage ---
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
