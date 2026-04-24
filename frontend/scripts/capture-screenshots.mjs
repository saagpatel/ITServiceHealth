import puppeteer from "puppeteer-core";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const URL = "http://localhost:5173/";
const OUT_DIR = path.resolve(
  __dirname,
  "../docs/executive-view-redesign/screenshots",
);

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 2 },
  args: ["--disable-web-security", "--no-sandbox"],
});

async function captureOperational() {
  const page = await browser.newPage();
  await page.goto(URL, { waitUntil: "networkidle0" });
  await page.evaluate(() => localStorage.setItem("pulse-view-mode", "executive"));
  await page.reload({ waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="executive-view"]');
  await new Promise((r) => setTimeout(r, 3000)); // let trend fetch + hydrate
  const outPath = path.join(OUT_DIR, "exec-operational.png");
  await page.screenshot({ path: outPath, fullPage: true });
  console.log("wrote", outPath);
  await page.close();
}

async function captureMajor() {
  const page = await browser.newPage();
  await page.goto(URL, { waitUntil: "networkidle0" });
  await page.evaluate(() => localStorage.setItem("pulse-view-mode", "executive"));
  await page.reload({ waitUntil: "networkidle0" });
  await page.waitForSelector('[data-testid="executive-view"]');
  await new Promise((r) => setTimeout(r, 3000));

  // DOM mock of major_outage — documented artifact, not a data claim.
  // Kept in lock-step with ExecutiveStatusPanel / KpiTiles / ImpactList
  // class + text conventions; revisit if those components change.
  await page.evaluate(() => {
    const view = document.querySelector('[data-testid="executive-view"]');
    const panel = view.querySelector("section");
    const h2 = panel.querySelector("h2");
    const chip = panel.querySelector("span.inline-flex");
    const tiles = view.querySelectorAll('[class*="lg:grid-cols-3"] > div');
    const impactChips = view.querySelectorAll("ul > li .rounded-full");
    const impactLines = view.querySelectorAll("ul > li p");
    const impactLabels = view.querySelectorAll("ul > li .text-lede");

    panel.className = panel.className.replace(
      "bg-surface-elev-1",
      "bg-accent-alarm",
    );
    h2.textContent = "3 Active Incidents";
    chip.lastChild.textContent = " Major Outage";
    tiles[0].children[1].textContent = "3";
    tiles[1].children[1].textContent = "3";

    const mockImpact = [
      {
        label: "Slack",
        status: "Major Outage",
        line: "Slack messaging is unavailable — affecting internal collaboration and incident channels.",
      },
      {
        label: "Okta",
        status: "Partial Outage",
        line: "Okta sign-in is degraded — affecting SSO for downstream SaaS.",
      },
      {
        label: "Zoom",
        status: "Degraded",
        line: "Zoom video quality is reduced — meetings may experience jitter.",
      },
    ];

    impactChips.forEach((c, i) => {
      if (i < 3) {
        c.className = c.className.replace(
          "bg-surface-elev-2 text-text-dim",
          "bg-accent-alarm/20 text-accent-alarm",
        );
        c.textContent = mockImpact[i].status;
      }
    });
    impactLabels.forEach((l, i) => {
      if (i < 3) l.textContent = mockImpact[i].label;
    });
    impactLines.forEach((p, i) => {
      if (i < 3) p.textContent = mockImpact[i].line;
    });
  });

  const outPath = path.join(OUT_DIR, "exec-major.png");
  await page.screenshot({ path: outPath, fullPage: true });
  console.log("wrote", outPath);
  await page.close();
}

await captureOperational();
await captureMajor();

await browser.close();
