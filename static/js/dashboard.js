const liveBatches = document.querySelectorAll(
    '[data-batch-status="processing"]'
);

if (liveBatches.length > 0) {
    window.setTimeout(() => {
        window.location.reload();
    }, 8000);
}
