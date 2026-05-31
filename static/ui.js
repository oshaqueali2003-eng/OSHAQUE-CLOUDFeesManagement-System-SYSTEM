// ====================== OSHAQUE CLOUDFEES UI FUNCTIONS ======================

// Toast Notifications
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `ocb-toast ${type}`;
    toast.innerHTML = `<i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'}"></i> ${message}`;
    container.appendChild(toast);
    
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Loading Spinner
window.OCB_LOADING = {
    set: function(btn, loading, originalText = null) {
        if (!originalText) originalText = btn.innerHTML;
        if (loading) {
            btn.innerHTML = '<span class="ocb-spinner"></span> Processing...';
            btn.disabled = true;
        } else {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
        return originalText;
    }
};

// Get Student Fees (AJAX)
function getStudentFees(studentId) {
    fetch(`/get_student_fees/${studentId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                displayFeeDetails(data);
            } else {
                showToast(data.error || 'Error loading fee details', 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Failed to load fee details', 'error');
        });
}

// Collect Fee
function collectFee(studentId) {
    const amount = document.getElementById('fee_amount').value;
    const paymentMode = document.getElementById('payment_mode').value;
    
    if (!amount || amount <= 0) {
        showToast('Please enter valid amount', 'warning');
        return;
    }
    
    fetch('/collect_fee', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
            student_id: studentId,
            amount: amount,
            payment_mode: paymentMode
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(`Payment successful! Receipt No: ${data.receipt_no}`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.error || 'Payment failed', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('Payment failed', 'error');
    });
}

// Send Reminder
function sendReminder(studentId) {
    fetch(`/send_reminder/${studentId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Reminder sent successfully', 'success');
            } else {
                showToast('Failed to send reminder', 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Failed to send reminder', 'error');
        });
}

function editStudent(studentId) {
    fetch(`/get_student/${studentId}`)
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showToast(data.error || 'Unable to load student details', 'error');
                return;
            }

            const student = data.student;
            const form = document.getElementById('editStudentForm');
            form.action = `/edit_student/${encodeURIComponent(student.student_id)}`;
            document.getElementById('editStudentName').value = student.name;
            document.getElementById('editStudentEmail').value = student.email;
            document.getElementById('editStudentPhone').value = student.phone;
            document.getElementById('editStudentRoll').value = student.roll_no;
            document.getElementById('editStudentParentName').value = student.parent_name;
            document.getElementById('editStudentParentPhone').value = student.parent_phone;
            document.getElementById('editStudentParentEmail').value = student.parent_email;
            document.getElementById('editStudentAddress').value = student.address;
            document.getElementById('editStudentCourse').value = student.course_id || '';
            document.getElementById('editStudentSemester').value = student.semester_id || '';
            openModal('editStudentModal');
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Unable to load student details', 'error');
        });
}

function editCourse(courseId) {
    fetch(`/get_course/${courseId}`)
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showToast(data.error || 'Unable to load course details', 'error');
                return;
            }

            const course = data.course;
            const form = document.getElementById('editCourseForm');
            form.action = `/edit_course/${course.id}`;
            document.getElementById('editCourseName').value = course.course_name;
            document.getElementById('editCourseCode').value = course.course_code;
            document.getElementById('editCourseDuration').value = course.duration_years;
            document.getElementById('editCourseActive').value = course.is_active ? '1' : '0';
            openModal('editCourseModal');
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Unable to load course details', 'error');
        });
}

function editUser(userId) {
    fetch(`/get_user/${userId}`)
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showToast(data.error || 'Unable to load user details', 'error');
                return;
            }

            const user = data.user;
            const form = document.getElementById('editUserForm');
            form.action = `/edit_user/${user.id}`;
            document.getElementById('editUsername').value = user.username;
            document.getElementById('editUserEmail').value = user.email;
            document.getElementById('editUserRole').value = user.role;
            document.getElementById('editUserActive').value = user.is_active ? '1' : '0';
            document.getElementById('editUserPassword').value = '';

            window.__editingUserId = user.id;
            openModal('editUserModal');
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Unable to load user details', 'error');
        });
}

function uploadEditedUserImage() {
    const userId = window.__editingUserId;
    if (!userId) {
        showToast('No user selected for image upload', 'warning');
        return;
    }

    const fileInput = document.getElementById('editUserImage');
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        showToast('Please select an image first', 'warning');
        return;
    }

    const formData = new FormData();
    formData.append('user_id', userId);
    formData.append('image', fileInput.files[0]);

    fetch('/api/upload_image', {
        method: 'POST',
        body: formData
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast('User image uploaded successfully', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            showToast(data.error || 'Upload failed', 'error');
        }
    })
    .catch(() => showToast('Upload failed', 'error'));
}


function sendBulkReminder() {
    fetch('/send_bulk_reminders')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(`Bulk reminders sent to ${data.sent || 0} recipients`, 'success');
            } else {
                showToast('Bulk reminder failed', 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Bulk reminder failed', 'error');
        });
}

// Update Setting
function updateSetting(key, value) {
    fetch('/update_setting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ key, value })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (key === 'theme') {
                document.body.setAttribute('data-theme', value);
            }
            showToast('Setting updated', 'success');
        }
    })
    .catch(error => console.error('Error:', error));
}

// Theme Toggle
function toggleTheme() {
    const current = document.body.getAttribute('data-theme');
    const newTheme = current === 'light' ? 'dark' : 'light';
    document.body.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateSetting('theme', newTheme);
}

// Delete Confirmation
function confirmDelete(url, message) {
    if (confirm(message || 'Are you sure you want to delete this?')) {
        window.location.href = url;
    }
}

// Close Modal
function closeModal() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.style.display = 'none';
    });
}

// Open Modal
function openModal(modalId) {
    document.getElementById(modalId).style.display = 'flex';
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Theme initialization
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.body.setAttribute('data-theme', savedTheme);
    // Brand initialization (gold | blue)
    const savedBrand = localStorage.getItem('brand') || 'gold';
    document.body.setAttribute('data-brand', savedBrand);
    
    // Sidebar toggle for mobile
    const toggleBtn = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }

    // Theme toggle button (sidebar)
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            toggleTheme();
        });
    }

    // Brand toggle (if present)
    const brandButtons = document.querySelectorAll('#brand-toggle, #auth-brand-toggle, .brand-toggle');
    const _toggleBrand = () => {
        const current = document.body.getAttribute('data-brand') || 'gold';
        const next = current === 'gold' ? 'blue' : 'gold';
        setBrand(next);
    };
    brandButtons.forEach(btn => {
        btn.addEventListener('click', _toggleBrand);
    });
    // Update any brand controls' labels
    const _updateBrandControls = () => {
        const current = document.body.getAttribute('data-brand') || 'gold';
        brandButtons.forEach(btn => {
            try {
                if (btn.id === 'auth-brand-toggle') {
                    btn.innerHTML = `<i class="fas fa-palette"></i> ${current === 'gold' ? 'Gold Brand' : 'Blue Brand'}`;
                } else {
                    btn.innerHTML = `<i class="fas fa-palette"></i> ${current === 'gold' ? 'Gold' : 'Blue'}`;
                }
            } catch (e) {}
        });
    };
    _updateBrandControls();
    
    // Close sidebar when clicking outside on mobile
    window.addEventListener('click', function(event) {
        if (!event.target.closest('.sidebar') && !event.target.closest('#sidebar-toggle') && sidebar && sidebar.classList.contains('open')) {
            sidebar.classList.remove('open');
        }
    });
    
    // Close modals when clicking outside
    window.onclick = function(event) {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    };
});

// Expose a function to switch brand programmatically
function setBrand(brand) {
    document.body.setAttribute('data-brand', brand);
    localStorage.setItem('brand', brand);
    // reflect change on controls
    const brandButtons = document.querySelectorAll('#brand-toggle, #auth-brand-toggle, .brand-toggle');
    brandButtons.forEach(btn => {
        try {
            if (btn.id === 'auth-brand-toggle') {
                btn.innerHTML = `<i class="fas fa-palette"></i> ${brand === 'gold' ? 'Gold Brand' : 'Blue Brand'}`;
            } else {
                btn.innerHTML = `<i class="fas fa-palette"></i> ${brand === 'gold' ? 'Gold' : 'Blue'}`;
            }
        } catch (e) {}
    });
}