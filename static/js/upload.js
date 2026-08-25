const fileInput = document.querySelector("#parcel-images");
const fileCount = document.querySelector("#selected-file-count");
const submitButton = document.querySelector("#submit-button");

fileInput.addEventListener("change", () => {
    const numberOfFiles = fileInput.files.length;

    if (numberOfFiles === 0) {
        fileCount.textContent = "No images selected";
        submitButton.disabled = true;
        return;
    }

    if (numberOfFiles > 20) {
        fileCount.textContent = "Please select no more than 20 images";
        submitButton.disabled = true;
        return;
    }

    const imageWord = numberOfFiles === 1 ? "image" : "images";

    fileCount.textContent = `${numberOfFiles} ${imageWord} selected`;
    submitButton.disabled = false;
});