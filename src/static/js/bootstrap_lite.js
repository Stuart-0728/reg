(function () {
    if (window.bootstrap) {
        return;
    }

    function getTarget(selectorOrEl) {
        if (!selectorOrEl) return null;
        if (selectorOrEl instanceof Element) return selectorOrEl;
        const selector = String(selectorOrEl).trim();
        if (!selector) return null;
        try {
            return document.querySelector(selector);
        } catch (_) {
            return null;
        }
    }

    class Collapse {
        constructor(element) {
            this._element = getTarget(element);
        }

        show() {
            if (!this._element) return;
            this._element.classList.add('show');
        }

        hide() {
            if (!this._element) return;
            this._element.classList.remove('show');
        }

        toggle() {
            if (!this._element) return;
            this._element.classList.toggle('show');
        }
    }

    class Dropdown {
        constructor(toggleElement) {
            this._toggle = getTarget(toggleElement);
            this._menu = this._toggle ? this._toggle.parentElement.querySelector('.dropdown-menu') : null;
        }

        show() {
            if (!this._toggle || !this._menu) return;
            this._toggle.setAttribute('aria-expanded', 'true');
            this._menu.classList.add('show');
            this._toggle.parentElement.classList.add('show');
        }

        hide() {
            if (!this._toggle || !this._menu) return;
            this._toggle.setAttribute('aria-expanded', 'false');
            this._menu.classList.remove('show');
            this._toggle.parentElement.classList.remove('show');
        }

        toggle() {
            if (!this._menu) return;
            if (this._menu.classList.contains('show')) {
                this.hide();
            } else {
                closeAllDropdowns();
                this.show();
            }
        }
    }

    class Modal {
        constructor(element) {
            this._element = getTarget(element);
            this._backdrop = null;
        }

        _ensureBackdrop() {
            if (this._backdrop) return;
            const backdrop = document.createElement('div');
            backdrop.className = 'modal-backdrop fade show';
            backdrop.addEventListener('click', () => this.hide());
            this._backdrop = backdrop;
            document.body.appendChild(backdrop);
        }

        show() {
            if (!this._element) return;
            this._element.style.display = 'block';
            this._element.removeAttribute('aria-hidden');
            this._element.classList.add('show');
            document.body.classList.add('modal-open');
            this._ensureBackdrop();
        }

        hide() {
            if (!this._element) return;
            this._element.classList.remove('show');
            this._element.setAttribute('aria-hidden', 'true');
            this._element.style.display = 'none';
            document.body.classList.remove('modal-open');
            if (this._backdrop && this._backdrop.parentNode) {
                this._backdrop.parentNode.removeChild(this._backdrop);
            }
            this._backdrop = null;
        }

        toggle() {
            if (!this._element) return;
            if (this._element.classList.contains('show')) {
                this.hide();
            } else {
                this.show();
            }
        }
    }

    class Alert {
        constructor(element) {
            this._element = getTarget(element);
        }

        close() {
            if (!this._element) return;
            this._element.classList.remove('show');
            this._element.classList.add('hide');
            setTimeout(() => {
                if (this._element && this._element.parentNode) {
                    this._element.parentNode.removeChild(this._element);
                }
            }, 150);
        }
    }

    class Tooltip {
        constructor() {}
        show() {}
        hide() {}
        dispose() {}
    }

    function closeAllDropdowns() {
        document.querySelectorAll('.dropdown-menu.show').forEach((menu) => {
            menu.classList.remove('show');
            const parent = menu.parentElement;
            if (parent) {
                parent.classList.remove('show');
                const toggle = parent.querySelector('[data-bs-toggle="dropdown"]');
                if (toggle) {
                    toggle.setAttribute('aria-expanded', 'false');
                }
            }
        });
    }

    document.addEventListener('click', function (e) {
        const dropdownToggle = e.target.closest('[data-bs-toggle="dropdown"]');
        if (dropdownToggle) {
            e.preventDefault();
            const dropdown = new Dropdown(dropdownToggle);
            dropdown.toggle();
            return;
        }

        const collapseToggle = e.target.closest('[data-bs-toggle="collapse"]');
        if (collapseToggle) {
            e.preventDefault();
            const target = collapseToggle.getAttribute('data-bs-target') || collapseToggle.getAttribute('href');
            const collapse = new Collapse(target);
            collapse.toggle();
            const expanded = collapseToggle.getAttribute('aria-expanded') === 'true';
            collapseToggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            return;
        }

        const modalToggle = e.target.closest('[data-bs-toggle="modal"]');
        if (modalToggle) {
            e.preventDefault();
            const target = modalToggle.getAttribute('data-bs-target') || modalToggle.getAttribute('href');
            const modal = new Modal(target);
            modal.show();
            return;
        }

        const dismissModalBtn = e.target.closest('[data-bs-dismiss="modal"]');
        if (dismissModalBtn) {
            const modalEl = dismissModalBtn.closest('.modal');
            if (modalEl) {
                const modal = new Modal(modalEl);
                modal.hide();
            }
            return;
        }

        const dismissAlertBtn = e.target.closest('[data-bs-dismiss="alert"]');
        if (dismissAlertBtn) {
            const alertEl = dismissAlertBtn.closest('.alert');
            if (alertEl) {
                const alertObj = new Alert(alertEl);
                alertObj.close();
            }
            return;
        }

        if (!e.target.closest('.dropdown')) {
            closeAllDropdowns();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            closeAllDropdowns();
            document.querySelectorAll('.modal.show').forEach((modalEl) => {
                const modal = new Modal(modalEl);
                modal.hide();
            });
        }
    });

    window.bootstrap = {
        Collapse,
        Dropdown,
        Modal,
        Alert,
        Tooltip
    };
})();
