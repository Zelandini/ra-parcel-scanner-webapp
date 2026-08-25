const uploadForm = document.querySelector("#batch-upload-form");
const fileInput = document.querySelector("#parcel-images");
const fileCount = document.querySelector("#selected-file-count");
const submitButton = document.querySelector("#submit-button");
const csrfToken = document.querySelector("#csrf-token").value;
const progressPanel = document.querySelector("#progress-panel");
const progressTitle = document.querySelector("#progress-title");
const progressFraction = document.querySelector("#progress-fraction");
const progressTrack = document.querySelector(".progress-track");
const progressFill = document.querySelector("#progress-fill");
const progressSummary = document.querySelector("#progress-summary");
const statusList = document.querySelector("#upload-status-list");
const readyPanel = document.querySelector("#ready-panel");
const readyTitle = document.querySelector("#ready-title");
const readySummary = document.querySelector("#ready-summary");
const reviewLink = document.querySelector("#review-batch-link");

const maxImages = Number(uploadForm.dataset.maxImages);
const concurrency = 2;

let completedCount = 0;
let readyCount = 0;
let failedCount = 0;


function setProgress(total) {
    const percentage = total === 0
        ? 0
        : Math.round((completedCount / total) * 100);

    progressFraction.textContent = `${completedCount} of ${total}`;
    progressFill.style.width = `${percentage}%`;
    progressTrack.setAttribute("aria-valuenow", String(percentage));
    progressSummary.textContent = (
        `${readyCount} ready · ${failedCount} failed · `
        + `${total - completedCount} remaining`
    );
}


function createStatusRows(files) {
    statusList.replaceChildren();

    files.forEach((file, index) => {
        const item = document.createElement("li");
        item.dataset.index = String(index);

        const name = document.createElement("span");
        name.className = "upload-file-name";
        name.textContent = file.name;

        const status = document.createElement("span");
        status.className = "upload-item-status upload-waiting";
        status.textContent = "Waiting";

        item.append(name, status);
        statusList.append(item);
    });
}


function updateStatus(index, text, className) {
    const row = statusList.querySelector(`[data-index="${index}"]`);
    const status = row.querySelector(".upload-item-status");

    status.className = `upload-item-status ${className}`;
    status.textContent = text;
}


async function readJson(response) {
    try {
        return await response.json();
    } catch (error) {
        return {error: "The server returned an unexpected response."};
    }
}


async function uploadImage(file, index, itemUrl, total) {
    updateStatus(index, "Uploading and reading label…", "upload-processing");
    progressTitle.textContent = `Reading parcel ${index + 1}…`;

    const formData = new FormData();
    formData.append("parcel_image", file);

    try {
        const response = await fetch(itemUrl, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken
            },
            body: formData
        });

        const result = await readJson(response);

        if (!response.ok || result.status === "failed") {
            throw new Error(result.error || "Processing failed");
        }

        readyCount += 1;
        updateStatus(
            index,
            result.match_status === "confirmed"
                ? "Ready · confirmed match"
                : "Ready · human check needed",
            "upload-ready"
        );

    } catch (error) {
        failedCount += 1;
        updateStatus(index, "Failed · check on desktop", "upload-failed");

    } finally {
        completedCount += 1;
        setProgress(total);
    }
}


async function runUploadQueue(files, itemUrl) {
    let nextIndex = 0;

    async function worker() {
        while (nextIndex < files.length) {
            const currentIndex = nextIndex;
            nextIndex += 1;

            await uploadImage(
                files[currentIndex],
                currentIndex,
                itemUrl,
                files.length
            );
        }
    }

    const workerCount = Math.min(concurrency, files.length);
    await Promise.all(
        Array.from({length: workerCount}, () => worker())
    );
}


fileInput.addEventListener("change", () => {
    const numberOfFiles = fileInput.files.length;

    if (numberOfFiles === 0) {
        fileCount.textContent = "No images selected";
        submitButton.disabled = true;
        return;
    }

    if (numberOfFiles > maxImages) {
        fileCount.textContent = (
            `Please select no more than ${maxImages} images`
        );
        submitButton.disabled = true;
        return;
    }

    const imageWord = numberOfFiles === 1 ? "image" : "images";
    fileCount.textContent = `${numberOfFiles} ${imageWord} selected`;
    submitButton.disabled = false;
});


uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const files = Array.from(fileInput.files);

    if (files.length === 0 || files.length > maxImages) {
        return;
    }

    completedCount = 0;
    readyCount = 0;
    failedCount = 0;

    submitButton.disabled = true;
    fileInput.disabled = true;
    progressPanel.hidden = false;
    readyPanel.hidden = true;
    progressTitle.textContent = "Creating temporary batch…";
    createStatusRows(files);
    setProgress(files.length);

    try {
        const createResponse = await fetch(uploadForm.dataset.createUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken
            },
            body: JSON.stringify({total_items: files.length})
        });

        const batch = await readJson(createResponse);

        if (!createResponse.ok) {
            throw new Error(batch.error || "The batch could not be created.");
        }

        await runUploadQueue(files, batch.item_url);

        progressTitle.textContent = "Finishing batch…";

        const finishResponse = await fetch(batch.finish_url, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken
            }
        });

        const finishedBatch = await readJson(finishResponse);

        if (!finishResponse.ok) {
            throw new Error(
                finishedBatch.error || "The batch could not be finished."
            );
        }

        progressTitle.textContent = "Processing complete";
        readyPanel.hidden = false;
        reviewLink.href = finishedBatch.review_url;

        if (finishedBatch.status === "upload_incomplete") {
            readyTitle.textContent = "Ready, with upload issues";
        } else {
            readyTitle.textContent = "Ready for human checking";
        }

        readySummary.textContent = (
            `${readyCount} parcel labels are ready and `
            + `${failedCount} need attention. `
            + "You can continue from a desktop."
        );

    } catch (error) {
        progressTitle.textContent = "Batch stopped";
        progressSummary.textContent = error.message;
        submitButton.disabled = false;
        fileInput.disabled = false;
    }
});
