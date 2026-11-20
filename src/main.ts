import "./app.css";
import "mapbox-gl/dist/mapbox-gl.css";
import App from "./App.svelte";

const target = document.getElementById("app");
if (!target) throw new Error("index.html is missing the #app element");

const app = new App({ target });

export default app;
