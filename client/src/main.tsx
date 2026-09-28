import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
// فونت وزیرمتن — self-host قبل از استایل‌های خودمان
import "vazirmatn/Vazirmatn-font-face.css";
import "./index.css";
import App from "./App.tsx";

// پیش‌نمایش UI بدون بک‌اند — فقط dev و با ‎?__mock=1
const boot = async () => {
  if (import.meta.env.DEV && new URLSearchParams(location.search).has("__mock")) {
    try {
      const { installMockApi } = await import("./dev/mockApi");
      installMockApi();
    } catch (e) {
      console.error("mock api failed:", e);
    }
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <BrowserRouter>
        {" "}
        <App />
      </BrowserRouter>
    </StrictMode>
  );
};

boot();
