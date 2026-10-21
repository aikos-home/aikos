import { render } from "preact";
import { App } from "./app";
import "./styles.css";

render(<App />, document.getElementById("app")!);

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}
