import axios from "axios";

const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const client = axios.create({ baseURL, timeout: 30000 });

export const api = {
  getKpis: () => client.get("/api/kpis").then((r) => r.data),
  getAnomalies: () => client.get("/api/anomalies").then((r) => r.data),
  getAnomalyDetail: (id) => client.get(`/api/anomalies/${id}`).then((r) => r.data),
  getForecast: () => client.get("/api/forecast").then((r) => r.data),
  generateBrief: (topN = 5) =>
    client.post("/api/brief", { top_n: topN }).then((r) => r.data),
};

export default api;
