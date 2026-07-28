import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      // Η κάμερα/OCR χρειάζονται δίκτυο ούτως ή άλλως (backend) — το SW
      // εδώ υπάρχει ΜΟΝΟ για installability, όχι για πλήρες offline mode.
      workbox: {
        // dev-only telemetry/backend calls ΔΕΝ πρέπει να μπουν σε cache.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            urlPattern: /^\/api\//,
            handler: "NetworkOnly",
          },
        ],
      },
      manifest: {
        name: "Ψηφιακό Πελατολόγιο Οχημάτων",
        short_name: "Πελατολόγιο",
        description:
          "Ψηφιακό Πελατολόγιο Οχημάτων (ΑΑΔΕ) για συνεργεία αυτοκινήτων.",
        lang: "el",
        start_url: "/",
        display: "standalone",
        background_color: "#0f172a",
        theme_color: "#0f172a",
        icons: [
          { src: "/pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "/pwa-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
    host: true, // ώστε να ανοίγει και από το κινητό στο ίδιο δίκτυο (LAN IP)

    // Proxy: το frontend προωθεί τα /api στο backend (Flask :5001).
    // Έτσι χρειάζεται ΕΝΑ μόνο tunnel (το :3000) για δοκιμή από κινητό —
    // το backend δεν εκτίθεται ξεχωριστά και δεν χρειάζεται CORS.
    proxy: {
      "/api": {
        target: "http://localhost:5001",
        changeOrigin: true,
      },
    },

    // TEST ONLY: επιτρέπει οποιοδήποτε host (π.χ. τυχαία διεύθυνση ngrok /
    // cloudflared). Αλλιώς το Vite μπλοκάρει με «Blocked request».
    // Για production άφησέ το εκτός ή βάλε συγκεκριμένους hosts.
    allowedHosts: true,
  },
  // `vite preview` (δοκιμή του production PWA build) έχει ΔΙΚΟ ΤΟΥ proxy —
  // δεν κληρονομεί το server.proxy παραπάνω.
  preview: {
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:5001",
        changeOrigin: true,
      },
    },
    allowedHosts: true,
  },
});
