import assert from "node:assert/strict";
import { getDocument, version } from "pdfjs-dist/legacy/build/pdf.mjs";

const minimalPdf = new TextEncoder().encode(
  "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n" +
    "2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n" +
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n" +
    "xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n" +
    "0000000058 00000 n \n0000000115 00000 n \n" +
    "trailer<</Size 4/Root 1 0 R>>\nstartxref\n186\n%%EOF\n",
);

const loadingTask = getDocument({ data: minimalPdf });
const document = await loadingTask.promise;
assert.equal(document.numPages, 1);
const page = await document.getPage(1);
const viewport = page.getViewport({ scale: 1 });
assert.equal(viewport.width, 200);
assert.equal(viewport.height, 200);
await loadingTask.destroy();
console.log(`PDF.js ${version}: one-page parse probe passed`);
