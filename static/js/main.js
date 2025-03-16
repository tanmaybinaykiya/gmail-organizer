// Email functionality
document.addEventListener('DOMContentLoaded', function() {
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
