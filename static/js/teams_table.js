function sortTable(columnIndex) {
    const container = document.getElementById("teams-table-container");
    const table = container.querySelector("table");
    if (!table) { console.error("Table not found!"); return; }

    // 1. Target the 'tbody' elements instead of 'tr'
    // We filter for 'team-group' to avoid sorting the 'empty' state tbody if it exists
    const bodies = Array.from(table.querySelectorAll("tbody.team-group"));

    const isAscending = table.dataset.sortDir !== "asc";
    table.dataset.sortDir = isAscending ? "asc" : "desc";

    console.log(`Sorting Column ${columnIndex} (via tbody groups) in ${isAscending ? 'ASC' : 'DESC'} order`);

    const sortedBodies = bodies.sort((a, b) => {
        // 2. We find the main-row inside each tbody to get the actual data cells
        const rowA = a.querySelector("tr:not([id^='details-'])");
        const rowB = b.querySelector("tr:not([id^='details-'])");

        if (!rowA || !rowB) return 0;

        const cellA = rowA.children[columnIndex];
        const cellB = rowB.children[columnIndex];

        const valA = cellA.getAttribute('data-value') || cellA.innerText.trim();
        const valB = cellB.getAttribute('data-value') || cellB.innerText.trim();

        // --- Your existing sorting logic logic ---
        if (!valA || valA === "-") return 1;
        if (!valB || valB === "-") return -1;

        const numA = parseFloat(valA.replace(/[^\d.-]/g, ''));
        const numB = parseFloat(valB.replace(/[^\d.-]/g, ''));

        if (!isNaN(numA) && !isNaN(numB) && !valA.includes('-')) {
            return isAscending ? numA - numB : numB - numA;
        }

        const comparison = valA.localeCompare(valB, undefined, {numeric: true, sensitivity: 'base'});
        return isAscending ? comparison : -comparison;
    });

    // 3. Re-append the entire TBODY groups to the table
    // In HTML, appending a tbody to a table moves the whole group
    sortedBodies.forEach(body => table.appendChild(body));

    console.log("Sort complete. Tbody groups re-appended.");
}

// Sort table by header click
// function sortTable(columnIndex) {
//     const container = document.getElementById("teams-table-container");
//     const table = container.querySelector("table");
//     if (!table) return;
//
//     const tbody = table.querySelector("tbody");
//     const rows = Array.from(tbody.querySelectorAll("tr"));
//
//     let isAscending;
//         if (table.dataset.sortCol === String(columnIndex)) {
//             // If clicking the same column again, toggle the existing direction
//             isAscending = table.dataset.sortDir !== "asc";
//         } else {
//             // If it's a new column: default to DESC for Status (col 5), ASC for others
//             isAscending = (columnIndex === 5) ? false : true;
//         }
//
//         table.dataset.sortDir = isAscending ? "asc" : "desc";
//         table.dataset.sortCol = columnIndex; // Track which column is active
//
//         const sortedRows = rows.sort((a, b) => {
//         let valA = (a.children[columnIndex].getAttribute('data-value') || a.children[columnIndex].innerText).trim();
//         let valB = (b.children[columnIndex].getAttribute('data-value') || b.children[columnIndex].innerText).trim();
//
//         // 1. Handle Empty values
//         if (!valA || valA === "-") return 1;
//         if (!valB || valB === "-") return -1;
//
//         // --- BRANCH A: STATUS COLUMN LOGIC (Index 5) ---
//         if (columnIndex === 5) {
//             // Extract the date part: "2_2024-05-10_21:30" -> "2024-05-10_21:30"
//             // We split by the first underscore and take everything after it
//             const timeA = valA.includes('_') ? valA.substring(valA.indexOf('_') + 1) : valA;
//             const timeB = valB.includes('_') ? valB.substring(valB.indexOf('_') + 1) : valB;
//
//             // Handle "No Fixture" (val is "0") - move to bottom
//             if (valA === "0") return 1;
//             if (valB === "0") return -1;
//
//             let comparison = timeA.localeCompare(timeB);
//
//             // Return based on click direction (Ascending = Earlier dates first)
//             return isAscending ? comparison : -comparison;
//         }
//
//         // 3. DEFAULT LOGIC (Other Columns)
//         let comparison = 0;
//         const numA = parseFloat(valA.replace(/[^\d.-]/g, ''));
//         const numB = parseFloat(valB.replace(/[^\d.-]/g, ''));
//
//         if (!isNaN(numA) && !isNaN(numB) && !valA.includes('-')) {
//             comparison = numA - numB;
//         } else {
//             comparison = valA.localeCompare(valB);
//         }
//
//         // Default secondary sort by name for other columns
//         if (comparison === 0 && columnIndex !== 0) {
//             const nameA = a.children[0].innerText.trim();
//             const nameB = b.children[0].innerText.trim();
//             return nameA.localeCompare(nameB);
//         }
//
//         return isAscending ? comparison : -comparison;
//     });
//
//     // 4. Visual Refresh: Clear and Re-add
//     tbody.innerHTML = ""; // Clear existing rows
//     sortedRows.forEach(row => tbody.appendChild(row));
// }

// Search bar filter
function filterTeams() {
    // 1. Get the search string
    const input = document.getElementById("teamSearchInput");
    const filter = input.value.toLowerCase();

    // 2. Get all rows in the table body
    const table = document.querySelector("#teams-table-container table");
    const rows = table.getElementsByTagName("tr");

    // 3. Loop through rows (starting at 1 to skip header)
    for (let i = 1; i < rows.length; i++) {
        // We look at the first column (the Name)
        const nameColumn = rows[i].getElementsByTagName("td")[0];

        if (nameColumn) {
            const textValue = nameColumn.textContent || nameColumn.innerText;

            // 4. Show if match, hide if not
            if (textValue.toLowerCase().indexOf(filter) > -1) {
                rows[i].style.display = "";
            } else {
                rows[i].style.display = "none";
            }
        }
    }
}

// open fixtures row for a team
function toggleFixturesRow(teamId, event) {
    const row = document.getElementById(`details-${teamId}`);
    const content = document.getElementById(`content-${teamId}`);

    if (row.style.display !== "none") {
        // 1. If the row is OPEN, we close it and STOP HTMX from firing
        row.style.display = "none";
        event.stopImmediatePropagation(); // This kills the HTMX request

        // 2. Reset the spinner so it's ready for next time
        content.innerHTML = `
            <div style="text-align: center; padding: 20px;">
                <div class="spinner"></div>
                <p>Fetching fixtures...</p>
            </div>`;
    } else {
        // 3. If the row is CLOSED, we just open it.
        // HTMX will naturally continue and fetch the data.
        row.style.display = "table-row";
    }
}