// function switchTab(element, tabId) {
//     // 1. Hide all tab content
//     const contents = document.querySelectorAll('.tab-content');
//     contents.forEach(content => content.style.display = 'none');
//
//     // 2. Remove "active" class from all buttons
//     const buttons = document.querySelectorAll('.tab-btn');
//     buttons.forEach(btn => btn.classList.remove('active'));
//
//     // 3. SPECIFIC FIX FOR TEAMS: Clear the old table so we see the loader
//     if (tabId === 'teams-tab') {
//         const container = document.getElementById('teams-table-container');
//         const template = document.getElementById('spinner-template');
//
//         // 1. Create a clone in memory (not on the page yet)
//         const clone = template.content.cloneNode(true);
//
//         // 2. Change the text inside the clone
//         const messageElement = clone.querySelector('.loader-text');
//         if (messageElement) {
//             messageElement.textContent = "Fetching Teams Registry...";
//         }
//
//         // 3. NOW put it into the container
//         container.innerHTML = ''; // Clear old content
//         container.appendChild(clone); // Inject the modified clone
//
//         // // Reset the content to show the loader immediately
//         // container.innerHTML = `
//         //     <div id="table-loader" style="text-align:center; padding: 50px;">
//         //         <div class="spinner"></div>
//         //         <p>Updating registry...</p>
//         //     </div>`;
//
//         // 4. LOCAL ERROR HANDLING: Listen for the HTMX request completion
//         element.addEventListener('htmx:afterRequest', function handler(evt) {
//         // Check if the request failed (4xx or 5xx status codes)
//             if (evt.detail.failed) {
//                 // 1. Find the elements already inside the container
//                 const spinner = container.querySelector('.spinner');
//                 const messageElement = container.querySelector('.loader-text');
//
//                 // 2. Hide the spinner
//                 if (spinner) spinner.style.display = 'none';
//
//                 // 3. Update the text and styling
//                 if (messageElement) {
//                     messageElement.innerHTML = `
//                         <strong style="color: #dc3545;">Error:</strong> Could not update the registry.<br>
//                         // Instead of location.reload(), trigger the button click again:
//                         <button class="tab-btn" onclick="document.querySelector('[data-hx-get*=\\'teams_list_partial\\']').click()" style="margin-top:10px;">
//                             Try Again
//                         </button>
//                     `;
//                 }
//             }
//             // Always clean up the listener
//             element.removeEventListener('htmx:afterRequest', handler);
//         });
//     }
//
//     // 5. Show the selected tab and mark button as active
//     document.getElementById(tabId).style.display = 'block';
//     element.classList.add('active');
// }

function switchTab(element, tabId) {
    // 1. Hide all tab content and deactivate buttons
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

    // 2. Show the current tab
    const currentTab = document.getElementById(tabId);
    if (currentTab) currentTab.style.display = 'block';
    element.classList.add('active');

    // 3. GENERIC LOADER LOGIC
    const targetSelector = element.getAttribute('data-hx-target');
    const container = document.querySelector(targetSelector);
    const template = document.getElementById('spinner-template');

    if (container && template) {
        // Clear previous content and inject loader
        const clone = template.content.cloneNode(true);

        // Optional: Customize text based on tab name
        const message = clone.querySelector('.loader-text');
        if (message) message.textContent = `Loading ${element.textContent.trim()}...`;

        container.innerHTML = '';
        container.appendChild(clone);

        // 4. Error Handling (One-time listener)
        element.addEventListener('htmx:afterRequest', function handler(evt) {
            if (evt.detail.failed) {
                const spinner = container.querySelector('.spinner');
                if (spinner) spinner.style.display = 'none';
                if (message) {
                    message.innerHTML = `<span style="color: #dc3545;">Error loading content.</span>`;
                }
            }
            element.removeEventListener('htmx:afterRequest', handler);
        }, { once: true });
    }
}