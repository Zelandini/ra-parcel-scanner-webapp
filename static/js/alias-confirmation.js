const aliasDialog = document.querySelector("#alias-confirmation-dialog");
const aliasMessage = document.querySelector("#alias-confirmation-message");
const aliasConfirmButton = document.querySelector("#confirm-alias-change");
const aliasCancelButton = document.querySelector("#cancel-alias-change");

let pendingAliasForm = null;


function aliasChangeDetails(form) {
    const action = form.dataset.aliasAction;
    const resident = form.dataset.residentName || "this resident";
    const aliasInput = (
        form.querySelector('[name="new_alias"]')
        || form.querySelector('[name="alias"]')
    );
    const alias = aliasInput
        ? aliasInput.value.trim()
        : form.dataset.aliasValue;

    if (action === "remove") {
        return {
            message: (
                `Are you sure you want to remove “${form.dataset.aliasValue}” `
                + `from ${resident}? It will stop affecting future matches.`
            ),
            button: "Yes, remove alias",
            danger: true
        };
    }

    if (action === "edit") {
        return {
            message: (
                `Are you sure you want to change “${form.dataset.aliasValue}” `
                + `to “${alias}” for ${resident}?`
            ),
            button: "Yes, update alias",
            danger: false
        };
    }

    return {
        message: (
            `Are you sure you want to save “${alias}” as an alias `
            + `for ${resident}?`
        ),
        button: "Yes, save alias",
        danger: false
    };
}


document.querySelectorAll("[data-alias-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        if (event.defaultPrevented || !form.reportValidity()) {
            return;
        }

        const residentId = form.querySelector('[name="resident_id"]');

        if (residentId && !residentId.value) {
            event.preventDefault();
            window.alert("Choose a resident before saving the alias.");
            return;
        }

        event.preventDefault();
        const details = aliasChangeDetails(form);

        if (!aliasDialog || typeof aliasDialog.showModal !== "function") {
            if (window.confirm(details.message)) {
                form.submit();
            }
            return;
        }

        pendingAliasForm = form;
        aliasMessage.textContent = details.message;
        aliasConfirmButton.textContent = details.button;
        aliasConfirmButton.classList.toggle("danger-button", details.danger);
        aliasConfirmButton.classList.toggle("primary-button", !details.danger);
        aliasDialog.showModal();
    });
});


if (aliasConfirmButton) {
    aliasConfirmButton.addEventListener("click", () => {
        const form = pendingAliasForm;
        pendingAliasForm = null;
        aliasDialog.close();

        if (form) {
            form.submit();
        }
    });
}


if (aliasCancelButton) {
    aliasCancelButton.addEventListener("click", () => {
        pendingAliasForm = null;
        aliasDialog.close();
    });
}


if (aliasDialog) {
    aliasDialog.addEventListener("click", (event) => {
        if (event.target === aliasDialog) {
            pendingAliasForm = null;
            aliasDialog.close();
        }
    });
}
