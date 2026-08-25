const filterButtons = document.querySelectorAll("[data-filter]");
const reviewCards = document.querySelectorAll(".review-card");

filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
        const selectedFilter = button.dataset.filter;

        filterButtons.forEach((otherButton) => {
            otherButton.classList.toggle(
                "is-active",
                otherButton === button
            );
        });

        reviewCards.forEach((card) => {
            const shouldShow = (
                selectedFilter === "all"
                || card.dataset.reviewStatus === selectedFilter
            );

            card.hidden = !shouldShow;
        });
    });
});


document.querySelectorAll(".resident-search").forEach((searchBox) => {
    const input = searchBox.querySelector(".resident-search-input");
    const button = searchBox.querySelector(".resident-search-button");
    const results = searchBox.querySelector(".resident-search-results");

    async function search() {
        const query = input.value.trim();

        if (query.length < 2) {
            results.textContent = "Enter at least two characters.";
            return;
        }

        button.disabled = true;
        results.textContent = "Searching…";

        try {
            const url = new URL(searchBox.dataset.searchUrl, window.location.origin);
            url.searchParams.set("q", query);

            const response = await fetch(url);
            const data = await response.json();

            results.replaceChildren();

            if (!response.ok || data.residents.length === 0) {
                results.textContent = "No residents found.";
                return;
            }

            data.residents.forEach((resident) => {
                const form = document.createElement("form");
                form.method = "POST";
                form.action = searchBox.dataset.selectUrl;
                form.className = "resident-search-result";

                const csrf = document.createElement("input");
                csrf.type = "hidden";
                csrf.name = "csrf_token";
                csrf.value = searchBox.dataset.csrfToken;

                const residentId = document.createElement("input");
                residentId.type = "hidden";
                residentId.name = "resident_id";
                residentId.value = resident.student_id;

                const description = document.createElement("span");
                description.textContent = (
                    `${resident.full_name} · ${resident.room}`
                );

                const selectButton = document.createElement("button");
                selectButton.type = "submit";
                selectButton.className = "text-button";
                selectButton.textContent = "Select";

                form.append(csrf, residentId, description, selectButton);
                results.append(form);
            });

        } catch (error) {
            results.textContent = "Resident search is unavailable.";

        } finally {
            button.disabled = false;
        }
    }

    button.addEventListener("click", search);
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            search();
        }
    });
});


async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
        return;
    }

    const temporaryInput = document.createElement("textarea");
    temporaryInput.value = value;
    temporaryInput.style.position = "fixed";
    temporaryInput.style.opacity = "0";
    document.body.append(temporaryInput);
    temporaryInput.select();
    document.execCommand("copy");
    temporaryInput.remove();
}


document.querySelectorAll(".copy-id-button").forEach((button) => {
    button.addEventListener("click", async () => {
        const originalLabel = button.textContent;

        try {
            await copyText(button.dataset.studentId);
            button.textContent = "Copied";
            button.classList.add("is-copied");

            window.setTimeout(() => {
                button.textContent = originalLabel;
                button.classList.remove("is-copied");
            }, 1400);

        } catch (error) {
            button.textContent = "Copy failed";
        }
    });
});
