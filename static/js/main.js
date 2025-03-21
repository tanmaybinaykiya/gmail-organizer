// Email functionality
document.addEventListener('DOMContentLoaded', function() {
    // Global variables for pagination
    let nextPageToken = null;
    let currentEmailCount = document.querySelectorAll('.email-item').length;
    let isFetching = false;
    let totalUnreadCount = parseInt(document.querySelector('.unread-count').textContent.match(/\d+/)[0] || '0');
    let isBackgroundFetching = document.body.getAttribute('data-is-loading') === 'true';
    let lastUpdateTime = Date.now();
    let updateInterval = null;
    let initialLoadComplete = false;
    let isPaused = false;
    let selectedEmailCount = 0; // Track number of selected emails

    // Store domain pagination state
    const domainPagination = {};
    const EMAILS_PER_PAGE = 10; // Number of emails to show per page for each domain

    // Function to update selected email count
    function updateSelectedCount() {
        const checkedEmails = document.querySelectorAll('.email-checkbox:checked');
        selectedEmailCount = checkedEmails.length;

        // Update the count display
        const selectedCountEl = document.getElementById('selected-count');
        if (selectedCountEl) {
            selectedCountEl.textContent = `(${selectedEmailCount} selected)`;
        }

        // Enable/disable the apply button
        const applyBtn = document.getElementById('apply-action-btn');
        if (applyBtn) {
            applyBtn.disabled = selectedEmailCount === 0;
        }
    }

    // Setup collapsible domain sections
    function setupCollapsibleDomains() {
        const domainHeaders = document.querySelectorAll('.domain-header');

        domainHeaders.forEach(header => {
            if (!header.hasEventListener) {
                header.hasEventListener = true;
                header.addEventListener('click', function(e) {
                    // Don't collapse if clicking on checkbox
                    if (e.target.closest('.domain-checkbox')) {
                        return;
                    }

                    const domainSection = this.closest('.domain-section');
                    domainSection.classList.toggle('collapsed');

                    // Store collapsed state in localStorage
                    const domain = domainSection.getAttribute('data-domain');
                    const collapsedDomains = JSON.parse(localStorage.getItem('collapsedDomains') || '{}');

                    if (domainSection.classList.contains('collapsed')) {
                        collapsedDomains[domain] = true;
                    } else {
                        delete collapsedDomains[domain];
                    }

                    localStorage.setItem('collapsedDomains', JSON.stringify(collapsedDomains));
                });
            }
        });

        // Apply saved collapsed states
        const collapsedDomains = JSON.parse(localStorage.getItem('collapsedDomains') || '{}');
        for (const domain in collapsedDomains) {
            const domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);
            if (domainSection) {
                domainSection.classList.add('collapsed');
            }
        }
    }

    // Initialize pagination for a domain
    function initDomainPagination(domain) {
        if (!domainPagination[domain]) {
            domainPagination[domain] = {
                currentPage: 1,
                totalPages: 1,
                selectedEmails: new Set() // Track selected emails by ID
            };
        }

        const domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);
        if (!domainSection) return;

        const emailItems = domainSection.querySelectorAll('.email-item');
        const totalEmails = emailItems.length;
        const totalPages = Math.ceil(totalEmails / EMAILS_PER_PAGE);

        domainPagination[domain].totalPages = totalPages;

        // Create or update pagination controls
        let paginationContainer = domainSection.querySelector('.domain-pagination');
        if (!paginationContainer) {
            paginationContainer = document.createElement('div');
            paginationContainer.className = 'domain-pagination';

            // Add pagination container after email items
            const emailItemsContainer = domainSection.querySelector('.email-items');
            if (emailItemsContainer) {
                emailItemsContainer.after(paginationContainer);
            }
        }

        // Only show pagination if there are multiple pages
        if (totalPages <= 1) {
            paginationContainer.style.display = 'none';
            return;
        } else {
            paginationContainer.style.display = 'flex';
        }

        // Update pagination controls
        paginationContainer.innerHTML = `
            <div class="domain-pagination-info">
                Showing page ${domainPagination[domain].currentPage} of ${totalPages}
            </div>
            <div class="domain-pagination-controls">
                <button class="domain-pagination-button prev-page" ${domainPagination[domain].currentPage === 1 ? 'disabled' : ''}>
                    <i class="fas fa-chevron-left"></i> Prev
                </button>
                <div class="domain-pagination-page">${domainPagination[domain].currentPage} / ${totalPages}</div>
                <button class="domain-pagination-button next-page" ${domainPagination[domain].currentPage === totalPages ? 'disabled' : ''}>
                    Next <i class="fas fa-chevron-right"></i>
                </button>
            </div>
        `;

        // Add event listeners to pagination buttons
        const prevButton = paginationContainer.querySelector('.prev-page');
        const nextButton = paginationContainer.querySelector('.next-page');

        prevButton.addEventListener('click', function() {
            if (domainPagination[domain].currentPage > 1) {
                changePage(domain, domainPagination[domain].currentPage - 1);
            }
        });

        nextButton.addEventListener('click', function() {
            if (domainPagination[domain].currentPage < totalPages) {
                changePage(domain, domainPagination[domain].currentPage + 1);
            }
        });

        // Show the current page
        showDomainPage(domain, domainPagination[domain].currentPage);
    }

    // Change page for a domain
    function changePage(domain, pageNumber) {
        if (!domainPagination[domain]) return;

        // Save current page's selected emails
        saveSelectedEmails(domain);

        // Update current page
        domainPagination[domain].currentPage = pageNumber;

        // Show the new page
        showDomainPage(domain, pageNumber);

        // Update pagination controls
        const domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);
        if (!domainSection) return;

        const paginationInfo = domainSection.querySelector('.domain-pagination-info');
        if (paginationInfo) {
            paginationInfo.textContent = `Showing page ${pageNumber} of ${domainPagination[domain].totalPages}`;
        }

        const paginationPage = domainSection.querySelector('.domain-pagination-page');
        if (paginationPage) {
            paginationPage.textContent = `${pageNumber} / ${domainPagination[domain].totalPages}`;
        }

        const prevButton = domainSection.querySelector('.prev-page');
        if (prevButton) {
            prevButton.disabled = pageNumber === 1;
        }

        const nextButton = domainSection.querySelector('.next-page');
        if (nextButton) {
            nextButton.disabled = pageNumber === domainPagination[domain].totalPages;
        }
    }

    // Show a specific page for a domain
    function showDomainPage(domain, pageNumber) {
        const domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);
        if (!domainSection) return;

        const emailItems = domainSection.querySelectorAll('.email-item');
        const startIndex = (pageNumber - 1) * EMAILS_PER_PAGE;
        const endIndex = startIndex + EMAILS_PER_PAGE;

        // Hide all emails first
        emailItems.forEach((item, index) => {
            if (index >= startIndex && index < endIndex) {
                item.classList.remove('hidden-page');
            } else {
                item.classList.add('hidden-page');
            }
        });

        // Restore selected state for visible emails
        restoreSelectedEmails(domain);
    }

    // Save selected emails for a domain
    function saveSelectedEmails(domain) {
        const domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);
        if (!domainSection) return;

        // Clear previous selections for this domain
        domainPagination[domain].selectedEmails = new Set();

        // Save all checked emails
        const checkedEmails = domainSection.querySelectorAll('.email-checkbox:checked');
        checkedEmails.forEach(checkbox => {
            domainPagination[domain].selectedEmails.add(checkbox.value);
        });
    }

    // Restore selected emails for a domain
    function restoreSelectedEmails(domain) {
        if (!domainPagination[domain] || !domainPagination[domain].selectedEmails) return;

        const domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);
        if (!domainSection) return;

        // Get all visible email checkboxes
        const emailCheckboxes = domainSection.querySelectorAll('.email-item:not(.hidden-page) .email-checkbox');

        // Check the ones that were previously selected
        emailCheckboxes.forEach(checkbox => {
            if (domainPagination[domain].selectedEmails.has(checkbox.value)) {
                checkbox.checked = true;
            }
        });

        // Update domain checkbox state
        updateDomainCheckbox(domain);

        // Update total selected count
        updateSelectedCount();
    }

    // Initialize pagination for all domains
    function initAllDomainPagination() {
        const domainSections = document.querySelectorAll('.domain-section');
        domainSections.forEach(section => {
            const domain = section.getAttribute('data-domain');
            if (domain) {
                initDomainPagination(domain);
            }
        });
    }

    // Call setup on initial load
    setupCollapsibleDomains();
    initAllDomainPagination();

    // Fetch control elements
    const pauseBtn = document.getElementById('pause-fetch-btn');
    const resumeBtn = document.getElementById('resume-fetch-btn');
    const showLogsBtn = document.getElementById('show-logs-btn');
    const logsModal = document.getElementById('logs-modal');
    const closeModal = document.querySelector('.close-modal');
    const fetchStatusText = document.getElementById('fetch-status-text');
    const lastFetchTime = document.getElementById('last-fetch-time');
    const progressFill = document.querySelector('.progress-fill');

    // Set up status checking if background fetching is happening
    if (isBackgroundFetching) {
        // Start with a faster check interval for initial load
        updateInterval = setInterval(checkEmailStatus, 1000);

        // After 5 seconds, slow down the check interval to reduce server load
        setTimeout(function() {
            clearInterval(updateInterval);
            updateInterval = setInterval(checkEmailStatus, 3000);
        }, 5000);
    }

    // Function to check email status and update UI
    function checkEmailStatus() {
        // Don't check too frequently
        if (Date.now() - lastUpdateTime < 800) {
            return;
        }

        lastUpdateTime = Date.now();

        fetch('/fetch-status')
            .then(response => response.json())
            .then(data => {
                // Update the total count if needed
                if (data.total > 0 && data.total !== totalUnreadCount) {
                    totalUnreadCount = data.total;
                    document.querySelector('.unread-count span').textContent = `${totalUnreadCount} Unread Emails`;

                    const totalCountEl = document.getElementById('total-count');
                    if (totalCountEl) {
                        totalCountEl.textContent = totalUnreadCount;
                    }
                }

                // Update the fetched count
                if (data.fetched > currentEmailCount) {
                    const fetchedCountEl = document.getElementById('fetched-count');
                    if (fetchedCountEl) {
                        fetchedCountEl.textContent = data.fetched;
                    }

                    // Update the email list with new emails
                    updateEmailList(data.grouped);

                    // Setup collapsible functionality for new domains
                    setupCollapsibleDomains();

                    // Update current count
                    currentEmailCount = data.fetched;

                    // Update progress bar - use fetched count as percentage of total
                    // If total is 0, set progress to 100%
                    if (totalUnreadCount > 0) {
                        const progressPercent = Math.min((currentEmailCount / totalUnreadCount) * 100, 100);
                        progressFill.style.width = `${progressPercent}%`;
                    } else {
                        progressFill.style.width = '100%';
                    }

                    // If this is the first update after initial load, mark it complete
                    if (!initialLoadComplete && data.fetched > 0) {
                        initialLoadComplete = true;

                        // Hide any loading indicators
                        const loadingIndicators = document.querySelectorAll('.loading-indicator');
                        loadingIndicators.forEach(indicator => {
                            indicator.style.display = 'none';
                        });
                    }
                }

                // If total count is less than fetched count, update total to match fetched
                // This can happen if our initial estimate was too low
                if (totalUnreadCount < currentEmailCount) {
                    totalUnreadCount = currentEmailCount;
                    document.querySelector('.unread-count span').textContent = `${totalUnreadCount} Unread Emails`;

                    const totalCountEl = document.getElementById('total-count');
                    if (totalCountEl) {
                        totalCountEl.textContent = totalUnreadCount;
                    }

                    // Update progress bar to show 100% if we've fetched all emails
                    if (data.status === 'complete') {
                        progressFill.style.width = '100%';
                    }
                }

                // Update fetch status text and button states
                updateFetchStatusUI(data.status);

                // Update last fetch time if available
                if (data.last_fetch_time) {
                    lastFetchTime.textContent = formatTimeAgo(new Date(data.last_fetch_time));
                }

                // If fetching is complete or paused, stop checking frequently
                if (data.status === 'complete' || data.status === 'paused') {
                    if (updateInterval) {
                        clearInterval(updateInterval);
                        // Set a slower interval for occasional updates
                        updateInterval = setInterval(checkEmailStatus, 10000);
                    }

                    // Show load more button if there are more emails to fetch
                    const loadMoreBtn = document.getElementById('load-more-btn');
                    if (loadMoreBtn) {
                        if (data.status === 'paused' && currentEmailCount < totalUnreadCount) {
                            loadMoreBtn.style.display = 'block';
                        } else {
                            loadMoreBtn.style.display = 'none';
                        }
                    }

                    // Hide any loading indicators
                    const loadingIndicators = document.querySelectorAll('.loading-indicator');
                    loadingIndicators.forEach(indicator => {
                        indicator.style.display = 'none';
                    });
                }

                // Handle errors
                if (data.status === 'error') {
                    console.error('Error fetching emails:', data.error);
                    if (updateInterval) {
                        clearInterval(updateInterval);
                        updateInterval = null;
                    }
                }
            })
            .catch(error => {
                console.error('Error checking email status:', error);
            });
    }

    // Function to update the fetch status UI
    function updateFetchStatusUI(status) {
        // Remove all status classes
        fetchStatusText.classList.remove('fetching', 'paused', 'complete', 'error');

        // Update text and add appropriate class
        if (status === 'fetching') {
            fetchStatusText.textContent = 'Fetching';
            fetchStatusText.classList.add('fetching');
            pauseBtn.disabled = false;
            resumeBtn.disabled = true;
            isPaused = false;
        } else if (status === 'paused') {
            fetchStatusText.textContent = 'Paused';
            fetchStatusText.classList.add('paused');
            pauseBtn.disabled = true;
            resumeBtn.disabled = false;
            isPaused = true;
        } else if (status === 'complete') {
            fetchStatusText.textContent = 'Complete';
            fetchStatusText.classList.add('complete');
            pauseBtn.disabled = true;
            resumeBtn.disabled = true;
            isPaused = false;
        } else if (status === 'error') {
            fetchStatusText.textContent = 'Error';
            fetchStatusText.classList.add('error');
            pauseBtn.disabled = true;
            resumeBtn.disabled = false;
            isPaused = true;
        }
    }

    // Function to format time ago
    function formatTimeAgo(date) {
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);

        if (diffSec < 60) {
            return 'Just now';
        } else if (diffMin < 60) {
            return `${diffMin} minute${diffMin > 1 ? 's' : ''} ago`;
        } else if (diffHour < 24) {
            return `${diffHour} hour${diffHour > 1 ? 's' : ''} ago`;
        } else {
            return date.toLocaleString();
        }
    }

    // Event listeners for fetch control buttons
    if (pauseBtn) {
        pauseBtn.addEventListener('click', function() {
            if (!isPaused) {
                fetch('/pause-fetch', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'paused') {
                        updateFetchStatusUI('paused');
                        console.log('Email fetching paused');
                    }
                })
                .catch(error => {
                    console.error('Error pausing fetch:', error);
                });
            }
        });
    }

    if (resumeBtn) {
        resumeBtn.addEventListener('click', function() {
            if (isPaused) {
                fetch('/resume-fetch', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'fetching') {
                        updateFetchStatusUI('fetching');
                        console.log('Email fetching resumed');

                        // Restart the status checking interval
                        if (updateInterval) {
                            clearInterval(updateInterval);
                        }
                        updateInterval = setInterval(checkEmailStatus, 2000);
                    }
                })
                .catch(error => {
                    console.error('Error resuming fetch:', error);
                });
            }
        });
    }

    // Logs modal functionality
    if (showLogsBtn) {
        showLogsBtn.addEventListener('click', function() {
            // Fetch the latest logs
            fetch('/fetch-logs')
                .then(response => response.json())
                .then(data => {
                    // Update modal content
                    document.getElementById('modal-status').textContent = data.status;
                    document.getElementById('modal-fetched').textContent = data.fetched;
                    document.getElementById('modal-total').textContent = data.total;

                    if (data.last_fetch_time) {
                        document.getElementById('modal-last-update').textContent = data.last_fetch_time;
                    } else {
                        document.getElementById('modal-last-update').textContent = 'N/A';
                    }

                    // Handle error display with better error handling
                    const errorElement = document.getElementById('modal-error');
                    if (data.error) {
                        errorElement.textContent = data.error;
                        errorElement.style.color = 'var(--danger)';
                    } else {
                        errorElement.textContent = 'None';
                        errorElement.style.color = 'var(--gray)';
                    }

                    // Add domain count information if available
                    const domainInfoElement = document.getElementById('modal-domain-info');
                    if (domainInfoElement) {
                        if (data.domain_count !== undefined) {
                            domainInfoElement.textContent = data.domain_count;
                        } else {
                            domainInfoElement.textContent = 'N/A';
                        }
                    }

                    // Show the modal
                    logsModal.style.display = 'block';
                })
                .catch(error => {
                    console.error('Error fetching logs:', error);
                    // Show error in modal
                    document.getElementById('modal-status').textContent = 'Error';
                    document.getElementById('modal-error').textContent = 'Failed to fetch logs: ' + error.message;
                    document.getElementById('modal-error').style.color = 'var(--danger)';
                    logsModal.style.display = 'block';
                });
        });
    }

    // Close modal when clicking the X
    if (closeModal) {
        closeModal.addEventListener('click', function() {
            logsModal.style.display = 'none';
        });
    }

    // Close modal when clicking outside of it
    window.addEventListener('click', function(event) {
        if (event.target === logsModal) {
            logsModal.style.display = 'none';
        }
    });

    // Function to update the email list with new emails
    function updateEmailList(groupedEmails) {
        if (!groupedEmails) return;

        const emailListContent = document.querySelector('.email-list-content');

        // Process each domain group
        for (const domain in groupedEmails) {
            let domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);
            const emails = groupedEmails[domain];

            // If domain section doesn't exist, create it
            if (!domainSection) {
                domainSection = document.createElement('div');
                domainSection.className = 'domain-section';
                domainSection.setAttribute('data-domain', domain);

                domainSection.innerHTML = `
                    <div class="domain-header">
                        <div class="domain-checkbox">
                            <input type="checkbox" id="select-domain-${domain}" class="select-domain">
                            <label for="select-domain-${domain}"></label>
                        </div>
                        <h2 class="domain-name">${domain} <span class="email-count">(${emails.length})</span></h2>
                    </div>
                    <div class="email-items" id="domain-emails-${domain}"></div>
                `;

                // Find where to insert the new domain (by email count)
                const domainSections = Array.from(document.querySelectorAll('.domain-section'));
                let inserted = false;

                if (domainSections.length > 0) {
                    for (let i = 0; i < domainSections.length; i++) {
                        const section = domainSections[i];
                        const sectionDomain = section.getAttribute('data-domain');
                        const sectionCount = groupedEmails[sectionDomain] ? groupedEmails[sectionDomain].length : 0;

                        if (emails.length > sectionCount) {
                            section.parentNode.insertBefore(domainSection, section);
                            inserted = true;
                            break;
                        }
                    }
                }

                if (!inserted) {
                    // Insert before the load more container or at the end
                    const loadMoreContainer = document.querySelector('.load-more-container');
                    if (loadMoreContainer) {
                        emailListContent.insertBefore(domainSection, loadMoreContainer);
                    } else {
                        emailListContent.appendChild(domainSection);
                    }
                }

                // Add event listener for domain checkbox
                const domainCheckbox = domainSection.querySelector('.select-domain');
                domainCheckbox.addEventListener('change', function() {
                    const emailCheckboxes = document.querySelectorAll(`.email-checkbox[data-domain="${domain}"]`);
                    emailCheckboxes.forEach(cb => {
                        cb.checked = this.checked;
                    });
                });

                // Add collapsible functionality to new domain
                const domainHeader = domainSection.querySelector('.domain-header');
                domainHeader.addEventListener('click', function(e) {
                    // Don't collapse if clicking on checkbox
                    if (e.target.closest('.domain-checkbox')) {
                        return;
                    }

                    domainSection.classList.toggle('collapsed');

                    // Store collapsed state in localStorage
                    const collapsedDomains = JSON.parse(localStorage.getItem('collapsedDomains') || '{}');

                    if (domainSection.classList.contains('collapsed')) {
                        collapsedDomains[domain] = true;
                    } else {
                        delete collapsedDomains[domain];
                    }

                    localStorage.setItem('collapsedDomains', JSON.stringify(collapsedDomains));
                });

                // Apply saved collapsed state
                const collapsedDomains = JSON.parse(localStorage.getItem('collapsedDomains') || '{}');
                if (collapsedDomains[domain]) {
                    domainSection.classList.add('collapsed');
                }

                // Initialize pagination for the new domain
                initDomainPagination(domain);
            }

            // Get the email items container for this domain
            const emailItemsContainer = domainSection.querySelector('.email-items');
            const existingEmailIds = new Set(Array.from(emailItemsContainer.querySelectorAll('.email-item')).map(item => item.dataset.emailId));

            // Update the email count
            const emailCountElement = domainSection.querySelector('.email-count');

            // Add new emails that don't already exist
            for (const email of emails) {
                if (!existingEmailIds.has(email.id)) {
                    const emailItem = document.createElement('div');
                    emailItem.className = 'email-item';
                    emailItem.setAttribute('data-email-id', email.id);

                    emailItem.innerHTML = `
                        <div class="email-checkbox-container">
                            <input type="checkbox" id="email-${email.id}" class="email-checkbox" data-domain="${domain}" name="email_ids" value="${email.id}">
                            <label for="email-${email.id}"></label>
                        </div>
                        <div class="email-content">
                            <div class="email-sender">${email.sender}</div>
                            <div class="email-subject">${email.subject}</div>
                            <div class="email-date">${email.date}</div>
                        </div>
                    `;

                    emailItemsContainer.appendChild(emailItem);

                    // Add click event for preview
                    emailItem.addEventListener('click', handleEmailClick);

                    // Add change event for checkbox
                    const checkbox = emailItem.querySelector('.email-checkbox');
                    checkbox.addEventListener('change', function() {
                        updateDomainCheckbox(domain);

                        // Update selected count when checkbox changes
                        updateSelectedCount();
                    });

                    // Add to existing IDs set
                    existingEmailIds.add(email.id);
                }
            }

            // Update the count
            emailCountElement.textContent = `(${existingEmailIds.size})`;
        }

        // If there were no emails before, remove the "no emails" message
        const noEmailsMessage = document.querySelector('.no-emails');
        if (noEmailsMessage && Object.keys(groupedEmails).length > 0) {
            noEmailsMessage.remove();
        }

        // Re-sort domain sections by email count
        sortDomainSections();

        // Re-initialize pagination for all domains
        initAllDomainPagination();
    }

    // Function to sort domain sections by email count
    function sortDomainSections() {
        const emailListContent = document.querySelector('.email-list-content');
        const domainSections = Array.from(document.querySelectorAll('.domain-section'));
        const loadMoreContainer = document.querySelector('.load-more-container');

        // Remove all domain sections
        domainSections.forEach(section => section.remove());

        // Sort by email count
        domainSections.sort((a, b) => {
            const aCount = parseInt(a.querySelector('.email-count').textContent.match(/\d+/)[0] || '0');
            const bCount = parseInt(b.querySelector('.email-count').textContent.match(/\d+/)[0] || '0');
            return bCount - aCount;
        });

        // Re-insert in sorted order
        domainSections.forEach(section => {
            if (loadMoreContainer) {
                emailListContent.insertBefore(section, loadMoreContainer);
            } else {
                emailListContent.appendChild(section);
            }
        });
    }

    // Add load more button if needed
    const emailList = document.querySelector('.email-list-content');
    if (emailList) {
        // Check if load more container already exists
        let loadMoreContainer = document.querySelector('.load-more-container');

        if (!loadMoreContainer) {
            loadMoreContainer = document.createElement('div');
            loadMoreContainer.className = 'load-more-container';
            loadMoreContainer.innerHTML = `
                <button id="load-more-btn" class="load-more-btn">Load More Emails</button>
                <div class="loading-more" style="display: none;">
                    <div class="spinner"></div>
                    <span>Loading more emails...</span>
                </div>
                <div class="fetch-status">
                    <span id="fetched-count">${currentEmailCount}</span> of <span id="total-count">${totalUnreadCount}</span> emails loaded
                </div>
            `;
            emailList.appendChild(loadMoreContainer);
        }

        // Add event listener to load more button
        const loadMoreBtn = document.getElementById('load-more-btn');
        const loadingMore = document.querySelector('.loading-more');

        if (loadMoreBtn && !loadMoreBtn.hasEventListener) {
            loadMoreBtn.hasEventListener = true;
            loadMoreBtn.addEventListener('click', function() {
                if (isFetching) return;

                isFetching = true;
                loadMoreBtn.style.display = 'none';
                loadingMore.style.display = 'flex';

                fetchMoreEmails();
            });
        }

        // Hide button if we've loaded all emails
        if (loadMoreBtn && currentEmailCount >= totalUnreadCount) {
            loadMoreBtn.style.display = 'none';
        }
    }

    // Function to fetch more emails
    function fetchMoreEmails() {
        fetch(`/fetch-more?page_token=${nextPageToken || ''}&current_count=${currentEmailCount}`)
            .then(response => response.json())
            .then(data => {
                // Update next page token
                nextPageToken = data.next_page_token;

                // Update counts
                currentEmailCount += data.count;
                document.getElementById('fetched-count').textContent = currentEmailCount;

                // Add new emails to the list
                for (const domain in data.emails) {
                    let domainSection = document.querySelector(`.domain-section[data-domain="${domain}"]`);

                    // If domain section doesn't exist, create it
                    if (!domainSection) {
                        const domainContainer = document.createElement('div');
                        domainContainer.className = 'domain-section';
                        domainContainer.setAttribute('data-domain', domain);

                        domainContainer.innerHTML = `
                            <div class="domain-header">
                                <div class="domain-checkbox">
                                    <input type="checkbox" id="select-domain-${domain}" class="select-domain">
                                    <label for="select-domain-${domain}"></label>
                                </div>
                                <h2 class="domain-name">${domain} <span class="email-count">(${data.emails[domain].length})</span></h2>
                            </div>
                            <div class="email-items" id="domain-emails-${domain}"></div>
                        `;

                        // Insert at the end
                        const loadMoreContainer = document.querySelector('.load-more-container');
                        emailList.insertBefore(domainContainer, loadMoreContainer);

                        domainSection = domainContainer;
                    }

                    // Get the email items container for this domain
                    const emailItemsContainer = domainSection.querySelector('.email-items');

                    // Update the email count
                    const currentCount = parseInt(domainSection.querySelector('.email-count').textContent.match(/\d+/)[0] || '0');
                    domainSection.querySelector('.email-count').textContent = `(${currentCount + data.emails[domain].length})`;

                    // Add new emails
                    for (const email of data.emails[domain]) {
                        const emailItem = document.createElement('div');
                        emailItem.className = 'email-item';
                        emailItem.setAttribute('data-email-id', email.id);

                        emailItem.innerHTML = `
                            <div class="email-checkbox-container">
                                <input type="checkbox" id="email-${email.id}" class="email-checkbox" data-domain="${domain}" name="email_ids" value="${email.id}">
                                <label for="email-${email.id}"></label>
                            </div>
                            <div class="email-content">
                                <div class="email-sender">${email.sender}</div>
                                <div class="email-subject">${email.subject}</div>
                                <div class="email-date">${email.date}</div>
                            </div>
                        `;

                        emailItemsContainer.appendChild(emailItem);

                        // Add click event for preview
                        emailItem.addEventListener('click', handleEmailClick);

                        // Add change event for checkbox
                        const checkbox = emailItem.querySelector('.email-checkbox');
                        checkbox.addEventListener('change', function() {
                            updateDomainCheckbox(domain);

                            // Update selected count when checkbox changes
                            updateSelectedCount();
                        });
                    }
                }

                // Add event listeners to new checkboxes
                setupCheckboxes();

                // Re-sort domain sections by email count
                sortDomainSections();

                // Re-initialize pagination for all domains
                initAllDomainPagination();

                // Update UI
                const loadMoreBtn = document.getElementById('load-more-btn');
                const loadingMore = document.querySelector('.loading-more');

                loadingMore.style.display = 'none';
                isFetching = false;

                // Show load more button if there are more emails to fetch
                if (nextPageToken && currentEmailCount < totalUnreadCount) {
                    loadMoreBtn.style.display = 'block';
                } else {
                    loadMoreBtn.style.display = 'none';
                }
            })
            .catch(error => {
                console.error('Error fetching more emails:', error);

                const loadMoreBtn = document.getElementById('load-more-btn');
                const loadingMore = document.querySelector('.loading-more');

                loadingMore.style.display = 'none';
                loadMoreBtn.style.display = 'block';
                loadMoreBtn.textContent = 'Error loading emails. Try again';
                isFetching = false;
            });
    }

    // Function to handle email click
    function handleEmailClick() {
        const emailId = this.dataset.emailId;

        // Remove active class from previously active item
        if (activeEmailItem) {
            activeEmailItem.classList.remove('active');
        }

        // Add active class to clicked item
        this.classList.add('active');
        activeEmailItem = this;

        // Show loading spinner
        previewEmpty.style.display = 'none';
        previewContent.style.display = 'none';
        loading.style.display = 'flex';

        // On mobile, show the preview container
        if (window.innerWidth <= 768) {
            previewContainer.classList.add('active');
        }

        // Fetch email content
        fetch(`/email/${emailId}`)
            .then(response => response.json())
            .then(data => {
                // Hide loading spinner
                loading.style.display = 'none';

                // Update preview content
                previewSubject.textContent = data.subject;
                previewSender.textContent = data.sender;
                previewDate.textContent = data.date;
                previewTo.textContent = `To: ${data.to}`;
                previewBody.innerHTML = data.body;

                // Show preview content
                previewContent.style.display = 'flex';
            })
            .catch(error => {
                console.error('Error fetching email:', error);
                loading.style.display = 'none';
                previewEmpty.style.display = 'flex';
                previewEmpty.innerHTML = `
                    <i class="fas fa-exclamation-circle" style="color: var(--danger);"></i>
                    <h2>Error Loading Email</h2>
                    <p>There was a problem loading the email content.</p>
                `;
            });
    }

    // Function to set up checkbox event listeners
    function setupCheckboxes() {
        // Domain select all functionality
        const domainCheckboxes = document.querySelectorAll('.select-domain');
        domainCheckboxes.forEach(checkbox => {
            if (!checkbox.hasEventListener) {
                checkbox.hasEventListener = true;
                checkbox.addEventListener('change', function() {
                    const domainId = this.id.split('-').pop();
                    const emailCheckboxes = document.querySelectorAll(`.email-checkbox[data-domain="${domainId}"]`);

                    emailCheckboxes.forEach(cb => {
                        cb.checked = this.checked;
                    });

                    // Update selected count after changing checkboxes
                    updateSelectedCount();
                });
            }
        });

        // Individual email checkbox functionality
        const emailCheckboxes = document.querySelectorAll('.email-checkbox');
        emailCheckboxes.forEach(checkbox => {
            if (!checkbox.hasEventListener) {
                checkbox.hasEventListener = true;
                checkbox.addEventListener('change', function() {
                    const domainId = this.dataset.domain;
                    updateDomainCheckbox(domainId);

                    // Update selected count when checkbox changes
                    updateSelectedCount();
                });
            }
        });

        // After setting up checkboxes, restore selected state
        for (const domain in domainPagination) {
            restoreSelectedEmails(domain);
        }
    }

    // Initial setup of checkboxes
    setupCheckboxes();

    // Initial update of selected count
    updateSelectedCount();

    // Function to update domain checkbox state
    function updateDomainCheckbox(domainId) {
        const domainCheckbox = document.getElementById(`select-domain-${domainId}`);
        const emailCheckboxes = document.querySelectorAll(`.email-checkbox[data-domain="${domainId}"]`);

        let allChecked = true;
        let allUnchecked = true;

        emailCheckboxes.forEach(cb => {
            if (cb.checked) {
                allUnchecked = false;
            } else {
                allChecked = false;
            }
        });

        if (domainCheckbox) {
            domainCheckbox.checked = allChecked;
            domainCheckbox.indeterminate = !allChecked && !allUnchecked;
        }
    }

    // Email preview functionality
    const emailItems = document.querySelectorAll('.email-item');
    const previewEmpty = document.querySelector('.email-preview-empty');
    const previewContent = document.querySelector('.email-preview-content');
    const previewSubject = document.querySelector('.email-preview-subject');
    const previewSender = document.querySelector('.email-preview-sender');
    const previewDate = document.querySelector('.email-preview-date');
    const previewTo = document.querySelector('.email-preview-to');
    const previewBody = document.querySelector('.email-preview-body');
    const loading = document.querySelector('.loading');
    const previewContainer = document.querySelector('.email-preview-container');

    let activeEmailItem = null;

    // Add click event to existing email items
    emailItems.forEach(item => {
        item.addEventListener('click', handleEmailClick);
    });

    // Add close button for mobile view
    if (window.innerWidth <= 768) {
        const closeButton = document.createElement('div');
        closeButton.innerHTML = '<i class="fas fa-times"></i>';
        closeButton.style.position = 'absolute';
        closeButton.style.top = '10px';
        closeButton.style.right = '10px';
        closeButton.style.fontSize = '24px';
        closeButton.style.cursor = 'pointer';
        closeButton.style.zIndex = '1001';
        closeButton.style.color = 'var(--gray)';

        closeButton.addEventListener('click', function() {
            previewContainer.classList.remove('active');
        });

        previewContainer.appendChild(closeButton);
    }

    // Initial sort of domain sections
    sortDomainSections();
});
