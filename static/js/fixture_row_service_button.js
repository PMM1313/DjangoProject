/**
 * Fixture Settings Dropdown Handler
 * Encapsulated to prevent conflicts with other scripts
 */
(function() {
    // 1. Handle Clicks (Open/Toggle and Service Selection)
    document.addEventListener('click', function (e) {
        // Check if we clicked the Gear button
        const settingsBtn = e.target.closest('.btn-settings-square');

        // Check if we clicked an actual service button inside the menu
        const serviceBtn = e.target.closest('.dropdown-content button');

        // Logic for Gear Button (Toggle Menu)
        if (settingsBtn) {
            e.preventDefault();
            e.stopPropagation();

            const container = settingsBtn.closest('.settings-dropdown');
            const menu = container.querySelector('.dropdown-content');

            // Close all other open dropdowns first
            document.querySelectorAll('.dropdown-content.show').forEach(openMenu => {
                if (openMenu !== menu) openMenu.classList.remove('show');
            });

            menu.classList.toggle('show');
            return;
        }

        // Logic for Service Buttons (Close menu on click)
        if (serviceBtn) {
            const menu = serviceBtn.closest('.dropdown-content');
            if (menu) menu.classList.remove('show');
            // HTMX takes over from here via data-hx attributes
            return;
        }

        // If clicking anywhere else, close all open menus
        document.querySelectorAll('.dropdown-content.show').forEach(menu => {
            menu.classList.remove('show');
        });
    });

    // 2. Handle Mouse Leave (Auto-Close)
    document.addEventListener('mouseover', function (e) {
        const openMenu = document.querySelector('.dropdown-content.show');
        if (!openMenu) return;

        const container = openMenu.closest('.settings-dropdown');

        // Check if mouse left the container
        if (container && !container.contains(e.target)) {
            openMenu.classList.remove('show');
        }
    });
})();