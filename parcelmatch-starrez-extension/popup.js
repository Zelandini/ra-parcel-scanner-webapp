const sendButton = document.getElementById("sendButton");
const result = document.getElementById("result");

const parcelDot = document.getElementById("parcelDot");
const parcelStatus = document.getElementById("parcelStatus");

const starrezDot = document.getElementById("starrezDot");
const starrezStatus = document.getElementById("starrezStatus");

const residentsDot = document.getElementById("residentsDot");
const residentsStatus = document.getElementById("residentsStatus");

let readyStudentIds = [];
let isProcessing = false;

// ==================================================
// STATUS DISPLAY
// ==================================================

function setStatus(dot, text, ready, message) {
  dot.classList.remove("ready", "not-ready");
  text.classList.remove("ready-text", "not-ready-text");

  if (ready) {
    dot.classList.add("ready");
    text.classList.add("ready-text");
  } else {
    dot.classList.add("not-ready");
    text.classList.add("not-ready-text");
  }

  text.textContent = message;
}

// ==================================================
// CHECK EVERYTHING IS READY
// ==================================================

async function checkReadiness() {
  if (isProcessing) {
    return;
  }

  let parcelMatchReady = false;
  let starrezReady = false;

  readyStudentIds = [];

  // ==================================================
  // CHECK PARCELMATCH
  // ==================================================

  try {
    const [activeTab] = await chrome.tabs.query({
      active: true,
      currentWindow: true
    });

    const response = await chrome.scripting.executeScript({
      target: {
        tabId: activeTab.id
      },
      func: () => {
        const reviewList = document.querySelector(".review-list");

        if (!reviewList) {
          return {
            parcelMatch: false,
            studentIds: []
          };
        }

        const cards = document.querySelectorAll(
          '.review-card[data-review-status="confirmed"]'
        );

        const ids = [];

        for (const card of cards) {
          const button = card.querySelector(
            '.copy-id-button[data-student-id]'
          );

          if (button?.dataset.studentId) {
            ids.push(button.dataset.studentId);
          }
        }

        return {
          parcelMatch: true,
          studentIds: [...new Set(ids)].slice(0, 20)
        };
      }
    });

    const data = response[0].result;

    if (data?.parcelMatch) {
      parcelMatchReady = true;
      readyStudentIds = data.studentIds;

      setStatus(parcelDot, parcelStatus, true, "Ready");
    } else {
      setStatus(parcelDot, parcelStatus, false, "Open review page");
    }
  } catch (error) {
    setStatus(parcelDot, parcelStatus, false, "Open review page");
  }

  // ==================================================
  // CHECK STARREZ
  // ==================================================

  try {
    const starrezTabs = await chrome.tabs.query({
      url: "https://auckland.starrezhousing.com/*"
    });

    const directoryTab = starrezTabs.find(tab =>
      tab.url?.includes("/StarRezWeb/main/directory")
    );

    if (directoryTab) {
      starrezReady = true;
      setStatus(starrezDot, starrezStatus, true, "Ready");
    } else {
      setStatus(starrezDot, starrezStatus, false, "Not open");
    }
  } catch (error) {
    setStatus(starrezDot, starrezStatus, false, "Not open");
  }

  // ==================================================
  // CHECK CONFIRMED RESIDENTS
  // ==================================================

  if (parcelMatchReady && readyStudentIds.length > 0) {
    setStatus(
      residentsDot,
      residentsStatus,
      true,
      `${readyStudentIds.length} found`
    );
  } else {
    setStatus(residentsDot, residentsStatus, false, "None found");
  }

  // ==================================================
  // ENABLE BUTTON ONLY WHEN EVERYTHING IS READY
  // ==================================================

  const everythingReady =
    parcelMatchReady && starrezReady && readyStudentIds.length > 0;

  sendButton.disabled = !everythingReady;

  if (everythingReady) {
    sendButton.textContent = `Send ${readyStudentIds.length} Residents to StarRez`;
  } else {
    sendButton.textContent = "Waiting for required tabs...";
  }
}

// ==================================================
// SEND RESIDENTS
// ==================================================

sendButton.addEventListener("click", async () => {
  isProcessing = true;
  sendButton.disabled = true;
  result.textContent = "Reading confirmed ParcelMatch residents...";

  try {
    // ==================================================
    // GET CURRENT PARCELMATCH TAB
    // ==================================================

    const [parcelMatchTab] = await chrome.tabs.query({
      active: true,
      currentWindow: true
    });

    // ==================================================
    // READ CONFIRMED STUDENT IDS
    // ==================================================

    const parcelResponse = await chrome.scripting.executeScript({
      target: {
        tabId: parcelMatchTab.id
      },
      func: () => {
        const cards = document.querySelectorAll(
          '.review-card[data-review-status="confirmed"]'
        );

        const ids = [];

        for (const card of cards) {
          const button = card.querySelector(
            '.copy-id-button[data-student-id]'
          );

          if (button?.dataset.studentId) {
            ids.push(button.dataset.studentId);
          }
        }

        return ids;
      }
    });

    // Remove duplicates
    // Maximum 20 residents

    const studentIds = [...new Set(parcelResponse[0].result)].slice(0, 20);

    if (studentIds.length === 0) {
      throw new Error("No confirmed residents found.");
    }

    result.textContent =
      `${studentIds.length} residents found.\n` + `Looking for StarRez...`;

    // ==================================================
    // FIND STARREZ TAB
    // ==================================================

    const starrezTabs = await chrome.tabs.query({
      url: "https://auckland.starrezhousing.com/*"
    });

    if (starrezTabs.length === 0) {
      throw new Error("StarRez is not open.");
    }

    const starrezTab = starrezTabs.find(tab =>
      tab.url?.includes("/StarRezWeb/main/directory")
    );

    if (!starrezTab) {
      throw new Error("StarRez directory is not open.");
    }

    result.textContent = `Processing ${studentIds.length} residents...`;

    // ==================================================
    // RUN INSIDE STARREZ
    // ==================================================

    const starrezResponse = await chrome.scripting.executeScript({
      target: {
        tabId: starrezTab.id
      },
      args: [studentIds],
      func: async studentIds => {
        const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

        // ==================================
        // FIND STUDENT ROW
        // ==================================

        function findStudentRow(studentId) {
          const rows = document.querySelectorAll("tr");

          for (const row of rows) {
            const idLink = row.querySelector("td.ID1 a");

            if (idLink && idLink.textContent.trim() === studentId) {
              return row;
            }
          }

          return null;
        }

        // ==================================
        // SEARCH ONE STUDENT
        // ==================================

        async function searchStudent(studentId) {
          const searchBox = document.querySelector(
            'th[data-colkey="ID1"] input[name="ColumnFilter"]'
          );

          if (!searchBox) {
            throw new Error("Student search box not found");
          }

          // Clear previous search
          searchBox.focus();
          searchBox.value = "";
          searchBox.dispatchEvent(
            new Event("input", { bubbles: true })
          );

          // Enter Student ID
          searchBox.value = studentId;
          searchBox.dispatchEvent(
            new Event("input", { bubbles: true })
          );

          // Press Enter
          ["keydown", "keypress", "keyup"].forEach(type => {
            searchBox.dispatchEvent(
              new KeyboardEvent(type, {
                key: "Enter",
                code: "Enter",
                keyCode: 13,
                which: 13,
                bubbles: true,
                cancelable: true
              })
            );
          });

          // ==================================
          // WAIT FOR EXACT STUDENT
          // ==================================

          for (let i = 0; i < 60; i++) {
            const row = findStudentRow(studentId);

            if (row) {
              const checkbox = row.querySelector('input[type="checkbox"]');

              if (!checkbox) {
                throw new Error("Checkbox not found");
              }

              if (!checkbox.checked) {
                checkbox.click();
              }

              return;
            }

            await sleep(500);
          }

          throw new Error("Resident not found");
        }

        // ==================================
        // BATCH LOOP
        // ==================================

        const results = [];

        for (const studentId of studentIds) {
          try {
            await searchStudent(studentId);

            results.push({
              studentId: studentId,
              success: true
            });
          } catch (error) {
            results.push({
              studentId: studentId,
              success: false,
              error: error.message
            });
          }

          await sleep(500);
        }

        return results;
      }
    });

    // ==================================================
    // RESULTS
    // ==================================================

    const batchResults = starrezResponse[0].result;
    const successful = batchResults.filter(item => item.success);
    const failed = batchResults.filter(item => !item.success);

    let message =
      `Done!\n\n` +
      `✓ ${successful.length} selected\n` +
      `✗ ${failed.length} failed`;

    if (failed.length > 0) {
      message +=
        "\n\nFailed:\n" +
        failed.map(item => `${item.studentId}: ${item.error}`).join("\n");
    }

    result.textContent = message;
  } catch (error) {
    result.textContent = `Error: ${error.message}`;
  } finally {
    isProcessing = false;
    await checkReadiness();
  }
});

// ==================================================
// START CHECKING
// ==================================================

checkReadiness();
setInterval(checkReadiness, 1000);