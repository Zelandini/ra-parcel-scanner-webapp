const addAliasForm = document.querySelector("#add-alias-form");
const residentSearch = document.querySelector(".manager-resident-search");
const residentQuery = document.querySelector("#manager-resident-query");
const residentSearchButton = document.querySelector(
    "#manager-resident-search-button"
);
const residentResults = document.querySelector("#manager-resident-results");
const selectedResidentId = document.querySelector("#selected-resident-id");
const selectedResident = document.querySelector("#selected-resident");
const aliasFilter = document.querySelector("#alias-filter");
const aliasCards = document.querySelectorAll(".managed-alias-card");


async function searchManagerResidents() {
    const query = residentQuery.value.trim();

    if (query.length < 2) {
        residentResults.textContent = "Enter at least two characters.";
        return;
    }

    residentSearchButton.disabled = true;
    residentResults.textContent = "Searching…";

    try {
        const url = new URL(
            residentSearch.dataset.searchUrl,
            window.location.origin
        );
        url.searchParams.set("q", query);

        const response = await fetch(url);
        const data = await response.json();
        residentResults.replaceChildren();

        if (!response.ok || data.residents.length === 0) {
            residentResults.textContent = "No residents found.";
            return;
        }

        data.residents.forEach((resident) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "manager-resident-result";

            const name = document.createElement("strong");
            name.textContent = resident.full_name;

            const details = document.createElement("span");
            details.textContent = (
                `${resident.student_id} · ${resident.room}`
            );

            button.append(name, details);

            button.addEventListener("click", () => {
                selectedResidentId.value = resident.student_id;
                addAliasForm.dataset.residentName = resident.full_name;
                selectedResident.textContent = (
                    `Selected: ${resident.full_name} · ${resident.room}`
                );
                selectedResident.hidden = false;
                residentResults.replaceChildren();
            });

            residentResults.append(button);
        });

    } catch (error) {
        residentResults.textContent = "Resident search is unavailable.";

    } finally {
        residentSearchButton.disabled = false;
    }
}


residentSearchButton.addEventListener("click", searchManagerResidents);
residentQuery.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
        event.preventDefault();
        searchManagerResidents();
    }
});


aliasFilter.addEventListener("input", () => {
    const query = aliasFilter.value.trim().toLowerCase();

    aliasCards.forEach((card) => {
        card.hidden = (
            query.length > 0
            && !card.dataset.searchText.includes(query)
        );
    });
});
