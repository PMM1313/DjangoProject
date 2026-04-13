
// force full login page reload if user not loged
document.body.addEventListener("htmx:beforeOnLoad", function (evt) {
    // If the response is a 401 (Unauthorized) or a 302 (Redirect)
    // it means the session expired. Force a full page reload to the login page.
    if (evt.detail.xhr.status === 401 || evt.detail.xhr.status === 302) {
        window.location.href = "/login/"; // Or your specific login path
    }
});

// SHOW TOAST LOGIC and get new Alpine data
document.body.addEventListener("showToast", function(evt) {
    const data = evt.detail;
    const container = document.getElementById('toast-container');

    // 1. UPDATE THE TABLE DATA (The missing piece)
    // If the event contains new_data, update the Alpine store instantly
    if (data.new_data) {
        console.log("Toast received new data, updating table...");
        Alpine.store('distribution').initData(data.new_data);
    }

    // Safety check!
    if (!container) {
        console.warn("Toast container missing from HTML. Defaulting to alert.");
        alert(data.text);
        return;
    }

    const toast = document.createElement('div');
    toast.className = `toast-notification ${data.level}`;
    toast.innerText = data.text;

    container.appendChild(toast);

    // Cleanup logic
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 500);
    }, 4000);
});

// Catch system-level errors (404, 500, or Network Failure)
document.body.addEventListener('htmx:responseError', function(evt) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    // Get the error message from the server response
    // If the server didn't send text, fallback to a generic message
    const serverMessage = evt.detail.xhr.responseText;
    const errorText = serverMessage ? serverMessage : "A server error occurred.";

    const toast = document.createElement('div');
    toast.className = 'toast-notification error'; // This uses the Red CSS
    toast.innerText = errorText; // This will now show "Error: 'NoneType' object..."

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 500);
    }, 5000);
});

/**
 * Scans the table for headers that no longer have fixtures below them.
 */
document.body.addEventListener('htmx:beforeCleanupElement', function(evt) {
    const rowBeingDeleted = evt.target;

    if (rowBeingDeleted.classList.contains('fixture-row')) {
        const rowAbove = rowBeingDeleted.previousElementSibling;
        const rowBelow = rowBeingDeleted.nextElementSibling;

        // --- STEP 1: DATE CHECK ---
        if (rowAbove && rowAbove.classList.contains('date-row')) {
            const rowBelowIsFixture = rowBelow && rowBelow.classList.contains('fixture-row');

            if (!rowBelowIsFixture) {
                const leagueRowAbove = rowAbove.previousElementSibling;

                // --- STEP 2: LEAGUE CHECK ---
                if (leagueRowAbove && leagueRowAbove.classList.contains('league-row')) {
                    // It's empty if what follows is a NEW league, a NEW country, or nothing
                    const isLeagueEmpty = !rowBelow ||
                                         rowBelow.classList.contains('league-row') ||
                                         rowBelow.classList.contains('country-row');

                    if (isLeagueEmpty) {
                        const countryRowAbove = leagueRowAbove.previousElementSibling;

                        // --- STEP 3: COUNTRY CHECK ---
                        if (countryRowAbove && countryRowAbove.classList.contains('country-row')) {
                            // It's empty if what follows is a NEW country or nothing
                            const isCountryEmpty = !rowBelow ||
                                                   rowBelow.classList.contains('country-row');

                            if (isCountryEmpty) {
                                countryRowAbove.classList.add('row-fade-out');
                                setTimeout(() => countryRowAbove.remove(), 600);
                            }
                        }

                        // Remove League
                        leagueRowAbove.classList.add('row-fade-out');
                        setTimeout(() => leagueRowAbove.remove(), 600);
                    }
                }

                // Remove Date
                rowAbove.classList.add('row-fade-out');
                setTimeout(() => rowAbove.remove(), 600);
            }
        }
    }
});


function togglePlayButton(fixtureId) {
    const input = document.getElementById(`odds-input-${fixtureId}`);
    const button = document.getElementById(`play-btn-${fixtureId}`);

    // Just handle the boolean logic in JS
    button.disabled = !(input.value && parseFloat(input.value) > 0);
}

let collapsedDates = new Set(JSON.parse(localStorage.getItem('collapsedDates') || "[]"));
// This function remains exactly the same, but the 'dateId' passed to it
// will now be 'date-39-20260129' instead of just 'date-20260129' because id of league is in the date
function toggleDateGroup(dateId) {
    const rows = document.querySelectorAll('.' + dateId);
    const icon = document.getElementById('icon-' + dateId);
    if (rows.length === 0) return;

    const isCollapsing = rows[0].style.display !== "none";

    rows.forEach(row => {
        row.style.display = isCollapsing ? "none" : "table-row";
    });

    icon.innerText = isCollapsing ? "▶" : "▼";

    // Update the Set
    if (isCollapsing) {
        collapsedDates.add(dateId);
    } else {
        collapsedDates.delete(dateId);
    }

    // 2. SAVE to Local Storage (Convert Set to Array first because JSON can't stringify Sets)
    localStorage.setItem('collapsedDates', JSON.stringify(Array.from(collapsedDates)));
}

// 3. THE RE-BINDER (Now works for both HTMX swaps AND initial page load)
function applyCollapsedStates() {
    collapsedDates.forEach(dateId => {
        const rows = document.querySelectorAll('.' + dateId);
        const icon = document.getElementById('icon-' + dateId);
        rows.forEach(r => r.style.display = "none");
        if (icon) icon.innerText = "▶";
    });
}

// Run when HTMX swaps content
document.body.addEventListener('htmx:afterSwap', function(evt) {
    // Make sure this matches your container ID
    if (evt.detail.target.id === "fixture-container" || evt.detail.target.id === "main-table") {
        applyCollapsedStates();
    }
});

// Run when the page first loads
document.addEventListener('DOMContentLoaded', applyCollapsedStates);

// Get todays fixtures from table and show in summary div
// The JS logic
function toggleTodaySummary() {
    const container = document.getElementById('today-summary-container');
    const btn = document.getElementById('toggle-today-btn');

    // Check if we are opening or closing
    const isOpen = container.classList.contains('expanded');

    if (!isOpen) {
        // 1. Scan and fill content ONLY when opening
        renderTodayMatches();
        // 2. Then trigger the CSS animation
        container.classList.add('expanded');
        btn.innerText = "Hide Today's Matches";
    } else {
        // Close it
        container.classList.remove('expanded');
        btn.innerText = "Show Today's Matches";
    }
}

function toggleStreaksSummary() {
    const container = document.getElementById('teams-streaks-container');
    const btn = document.getElementById('toggle-streaks-btn');

    // If it's already expanded, we are clicking to HIDE it.
    if (container.classList.contains('streaks-expanded')) {
        container.classList.remove('streaks-expanded');
        container.classList.add('streaks-collapsed');
        btn.textContent = "Show Team's Streaks";
    }
    // If it's collapsed, the HTMX trigger will fire,
    // and we let the showLoader + CSS handle the opening.
    else {
        container.classList.remove('streaks-collapsed');
        container.classList.add('streaks-expanded');
        btn.textContent = "Hide Team's Streaks";
    }
}

function renderTodayMatches() {
    const content = document.getElementById('today-summary-content');
    content.innerHTML = ""; // Clear old data

    // Logic to find today's date (assuming your date format is YYYYMMDD)
    // Get YYYYMMDD the easy way
    const todayStr = new Intl.DateTimeFormat('en-CA').format(new Date()).replace(/-/g, '');

    const rows = document.querySelectorAll(`tr[class*="${todayStr}"]`);

    if (rows.length === 0) {
        content.innerHTML = "<p style='margin:0; color:#888;'>No matches scheduled for today.</p>";
        return;
    }

    rows.forEach(row => {
        // We clone only the specific parts of the row to keep it clean
        const time = row.querySelector('.fixture-time')?.innerText || "--:--";
        const home = row.querySelector('.team-home')?.innerText.trim();
        const away = row.querySelector('.team-away')?.innerText.trim();

        const matchItem = document.createElement('div');
        matchItem.className = 'summary-item';
        matchItem.innerHTML = `<span style="color: #007bff; font-weight: bold; min-width: 60px;">
                                    ${time}
                               </span> 
                               
                               <span>
                                    ${home} - ${away}
                               </span>`;
        content.appendChild(matchItem);
    });
}


/**
 * Reusable loader utility
 * @param {string} targetId - The ID of the element to fill with the loader
 * @param {string} message - The text to display below the spinner
 */
function showLoader(targetId, message = "Loading...") {
    const target = document.getElementById(targetId);
    const template = document.getElementById('spinner-template');

    if (!target || !template) return;

    const clone = template.content.cloneNode(true);
    const textElem = clone.querySelector('.loader-text');

    if (textElem) textElem.textContent = message;

    target.innerHTML = '';
    target.appendChild(clone);
}

// for the menu in action cell after the Play/Resolve button
function toggleKebabMenu(event, id) {
    // Prevent the click from bubbling up
    event.stopPropagation();

    // Close any other open menus first
    document.querySelectorAll('.kebab-dropdown').forEach(menu => {
        if (menu.id !== 'menu-' + id) menu.style.display = 'none';
    });

    // Toggle the clicked menu
    const menu = document.getElementById('menu-' + id);
    menu.style.display = (menu.style.display === 'none') ? 'block' : 'none';
}

// Close menus if user clicks anywhere else on the page
window.onclick = function(event) {
    if (!event.target.matches('.kebab-trigger') && !event.target.matches('.fa-ellipsis-v')) {
        document.querySelectorAll('.kebab-dropdown').forEach(menu => {
            menu.style.display = 'none';
        });
    }
}






