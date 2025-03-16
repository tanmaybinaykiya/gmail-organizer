// Email functionality
document.addEventListener('DOMContentLoaded', function() {
    // Global variables for pagination
    let nextPageToken = null;
    let currentEmailCount = document.querySelectorAll('.email-item').length;
    let isFetching = false;
    let totalUnreadCount = parseInt(document.querySelector('.unread-count').textContent.match(/\d+/)[0] || '0');

    // Add load more button if needed
    const emailList = document.querySelector('.email-list');
    if (emailList) {
        const loadMoreContainer = document.createElement('div');
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

        // Add event listener to load more button
        const loadMoreBtn = document.getElementById('load-more-btn');
        const loadingMore = document.querySelector('.loading-more');

        loadMoreBtn.addEventListener('click', function() {
            if (isFetching) return;

            isFetching = true;
            loadMoreBtn.style.display = 'none';
            loadingMore.style.display = 'flex';

            fetchMoreEmails();
        });

        // Hide button if we've loaded all emails
        if (currentEmailCount >= totalUnreadCount) {
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

                        // Find where to insert the new domain (alphabetically)
                        const domainSections = document.querySelectorAll('.domain-section');
                        let inserted = false;

                        for (const section of domainSections) {
                            const sectionDomain = section.getAttribute('data-domain');
                            if (domain < sectionDomain) {
                                section.parentNode.insertBefore(domainContainer, section);
                                inserted = true;
                                break;
                            }
                        }

                        if (!inserted) {
                            // Insert at the end
                            const loadMoreContainer = document.querySelector('.load-more-container');
                            emailList.insertBefore(domainContainer, loadMoreContainer);
                        }

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
                        emailItem.addEventListener('click', function() {
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
                        });
                    }
                }

                // Add event listeners to new checkboxes
                setupCheckboxes();

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
                });
            }
        });
    }

    // Initial setup of checkboxes
    setupCheckboxes();

    // Domain select all functionality
    const domainCheckboxes = document.querySelectorAll('.select-domain');
    domainCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const domainId = this.id.split('-').pop();
            const emailCheckboxes = document.querySelectorAll(`.email-checkbox[data-domain="${domainId}"]`);

            emailCheckboxes.forEach(cb => {
                cb.checked = this.checked;
            });
        });
    });

    // Individual email checkbox functionality
    const emailCheckboxes = document.querySelectorAll('.email-checkbox');
    emailCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const domainId = this.dataset.domain;
            updateDomainCheckbox(domainId);
        });
    });

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

    emailItems.forEach(item => {
        item.addEventListener('click', function() {
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
        });
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
});
