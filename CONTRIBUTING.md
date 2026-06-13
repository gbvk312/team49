# Contributing to team49

Thank you for your interest in contributing to team49! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Setting Up the Development Environment](#setting-up-the-development-environment)
- [Submitting Pull Requests](#submitting-pull-requests)
- [Code Style Guidelines](#code-style-guidelines)
- [Reporting Issues](#reporting-issues)

## Setting Up the Development Environment

### Prerequisites

- Python 3.12 or higher
- pip (Python package manager)
- Git

### Setup Steps

1. **Fork the repository** on GitHub.

2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-username>/team49.git
   cd team49
   ```

3. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Submitting Pull Requests

1. **Ensure your code is up to date** with the `master` branch:
   ```bash
   git fetch upstream
   git rebase upstream/master
   ```

2. **Write clear, concise commit messages** that describe your changes.

3. **Push your branch** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

4. **Open a Pull Request** against the `master` branch of this repository.

5. **In your PR description**, include:
   - A summary of the changes
   - The motivation or issue being addressed
   - Any relevant screenshots or test results

6. **Wait for review.** Maintainers will review your PR and may request changes.

## Code Style Guidelines

- Follow [PEP 8](https://peps.python.org/pep-0008/) for Python code style.
- Use meaningful variable and function names.
- Add docstrings to all public modules, classes, and functions.
- Keep functions focused and concise.
- Write unit tests for new functionality.
- Use type hints where appropriate.
- Maximum line length: 120 characters.

## Reporting Issues

When reporting issues, please include:

1. **A clear, descriptive title.**
2. **Steps to reproduce** the issue.
3. **Expected behavior** — what you expected to happen.
4. **Actual behavior** — what actually happened.
5. **Environment details** — OS, Python version, relevant package versions.
6. **Screenshots or logs** if applicable.

Use the [GitHub Issues](https://github.com/gbvk312/team49/issues) page to report bugs or request features.

---

Thank you for contributing! 🎉
