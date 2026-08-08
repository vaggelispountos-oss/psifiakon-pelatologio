import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { registerSW } from "virtual:pwa-register";
import App from "./App.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import "./App.css";

// registerType: "autoUpdate" (vite.config.js) ήδη ενεργοποιεί μόνο του τον
// νέο service worker σε background όταν βρεθεί update. Το explicit register
// εδώ με immediate:true απλά ξεκινά τον έλεγχο για update ΑΜΕΣΩΣ (όχι μόνο
// στο επόμενο navigation) — έτσι ένα tab που μένει ανοιχτό πολλή ώρα παίρνει
// το νέο build νωρίτερα, πριν προλάβει να ζητήσει chunk που δεν υπάρχει πια.
registerSW({ immediate: true });

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {/* Εξωτερικότερο δυνατό σημείο: πιάνει και σφάλμα του ίδιου του
        QueryClientProvider. Χωρίς αυτό, ΟΠΟΙΟΔΗΠΟΤΕ σφάλμα σε render
        αφήνει τον χρήστη με κατάλευκη σελίδα και μηδέν πληροφορία. */}
    <ErrorBoundary fullPage title="Η εφαρμογή σταμάτησε απρόσμενα">
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
