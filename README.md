# Asas School Backend

Backend API for the **Asas School Academic Platform**, built with Django and Django REST Framework.

The project provides the backend services required to manage the school's academic and administrative operations through secure REST APIs.

---

## Overview

Asas School Backend is a modular backend system designed for a single-school academic management platform.

The system manages several core domains, including:

* User accounts and roles
* Academic structure
* Students and enrollments
* Teachers and teacher assignments
* Attendance
* Homework
* Behavior notes
* Announcements
* Notifications
* Guardian requests
* Appointments
* Financial information

The backend serves both the web management system and the mobile application while applying role-based permissions according to each user type.

---

## Main Roles

The platform currently supports the following roles:

* School Admin
* Secretariat
* Educational Supervisor
* Teacher
* Guardian
* Technical Support

Permissions and data visibility are enforced at the backend level according to the user's role.

---

## Technology Stack

The backend is built using:

* Python
* Django
* Django REST Framework
* PostgreSQL
* SimpleJWT
* django-environ
* django-cors-headers
* django-filter
* drf-spectacular
* Pillow
* Gunicorn

Production services currently include:

* Render for backend hosting
* Neon PostgreSQL for the production database

---

## Project Structure

The project is organized into Django applications based on business domains.

Each application is responsible for a specific part of the school system and may contain:

* Models
* Serializers
* Views / ViewSets
* Permissions
* Services
* Policies
* Filters
* Tests
* URLs

The backend follows a modular monolith architecture to keep domain logic separated while maintaining straightforward deployment and development.

---

## Authentication

Authentication is based on JWT using SimpleJWT.

For the web application:

* Access and refresh tokens are stored using HttpOnly cookies.
* CSRF protection is enabled.
* Refresh token rotation is used.
* Refresh token blacklisting is enabled.
* Authentication endpoints are separated under the web authentication API.
* Tokens include additional security information such as token versioning.

Password lifecycle rules are also enforced, including temporary passwords and mandatory password changes where applicable.

---

## API Documentation

The project uses **drf-spectacular** to generate an OpenAPI schema.

Interactive API documentation is available through Swagger UI when enabled in the current environment.

The documentation can be used by:

* Backend developers
* Frontend developers
* Mobile developers
* QA engineers

to inspect endpoints, request bodies, responses, authentication requirements, and API schemas.

---

# Local Development

## 1. Clone the Repository

```bash
git clone <repository-url>
cd Asas-backend
```

Replace `<repository-url>` with the actual repository URL.

---

## 2. Create a Virtual Environment

### Windows

```powershell
python -m venv venv
```

Activate it:

```powershell
.\venv\Scripts\Activate.ps1
```

### Linux / macOS

```bash
python -m venv venv
source venv/bin/activate
```

---

## 3. Install Dependencies

Make sure the virtual environment is active.

Then run:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Verify that installed dependencies are consistent:

```bash
pip check
```

A healthy environment should return:

```text
No broken requirements found.
```

---

## 4. Environment Configuration

The project uses environment variables for configuration and sensitive information.

The local `.env` file must never be committed to Git.

Configure the required environment variables according to the project's current Django settings.

If an `.env.example` file is provided in the repository, use it as the reference for creating the local `.env` file.

Example workflow:

```text
.env.example
      ↓
.env
```

Never store production passwords, secret keys, database credentials, Firebase credentials, or other secrets directly in the source code.

---

## 5. Database Setup

Make sure the configured PostgreSQL database is available.

Apply Django migrations:

```bash
python manage.py migrate
```

Whenever models are intentionally changed, generate migrations first:

```bash
python manage.py makemigrations
```

Then apply them:

```bash
python manage.py migrate
```

Migration files should be reviewed before being committed, especially when they contain schema changes that may affect production data.

---

## 6. Run the Development Server

Start the Django development server:

```bash
python manage.py runserver
```

By default, Django will run locally at:

```text
http://127.0.0.1:8000/
```

The Django development server should only be used for local development.

---

# Testing

Tests should be executed from the project root while the virtual environment is active.

The project currently uses Django's testing infrastructure for backend verification.

Run the complete Django test suite using:

```bash
python manage.py test
```

Tests should cover critical backend behavior such as:

* Authentication
* Authorization
* Role permissions
* Password lifecycle
* Academic rules
* Enrollment operations
* Attendance rules
* Homework permissions
* Announcements
* Requests
* Finance calculations
* API validation
* Security-sensitive workflows

Before deploying important backend changes, the relevant automated tests and API flows should be verified.

Manual API testing can additionally be performed using Swagger UI or Postman.

---

# Production Deployment

The backend is currently deployed using **Render** with a PostgreSQL database hosted on **Neon**.

Production configuration must be provided using environment variables configured in the hosting environment.

Sensitive production values must never be committed to Git.

Typical deployment flow:

```text
Local development
        ↓
Tests and validation
        ↓
Git commit
        ↓
Push to main
        ↓
Render deployment
        ↓
Production verification
```

After deployment, verify at minimum:

* Application startup
* Database connection
* Migrations
* Authentication
* CORS
* CSRF
* API availability
* Swagger/OpenAPI availability when enabled
* Critical API endpoints
* Production logs

Database migrations should be handled carefully because production migrations may modify existing data or database structures.

---

# Security

Several security practices are applied to the project.

### Sensitive Files

The repository `.gitignore` prevents sensitive or local files from being tracked, including:

```text
.env
.env.*
venv/
.venv/
db.sqlite3
db.sqlite3-journal
media/
staticfiles/
firebase-service-account*.json
accounts_data.json
```

The `.env.example` file may be tracked when used as a safe configuration template.

Sensitive credentials must never be placed inside `.env.example`.

---

### Authentication Security

The backend uses security mechanisms including:

* JWT authentication
* HttpOnly cookies for web authentication
* CSRF protection
* Refresh token rotation
* Refresh token blacklisting
* Token versioning
* Authentication throttling
* Role-based permissions
* Temporary password expiration
* Forced password changes where required

---

### Authorization

Backend authorization must never depend only on frontend restrictions.

All sensitive operations must be protected through Django REST Framework permissions, queryset filtering, policies, services, or other backend-level authorization rules.

---

# Git Workflow

Before committing changes, inspect the repository state:

```bash
git status
```

Review changed files:

```bash
git diff
```

Stage the intended changes:

```bash
git add .
```

Create a commit:

```bash
git commit -m "your commit message"
```

Push the current branch:

```bash
git push
```

Sensitive files should always be checked before pushing changes to a remote repository.

---

# Planned Improvements

The following improvements are planned for future versions of the system:

### Custom Account Permissions

Extend administration capabilities so authorized administrative users can create accounts and assign approved custom permissions where required.

The permission architecture must be designed carefully before implementation to avoid conflicts between role-based and custom permissions.

### Excel Import / Export

Add controlled Excel import and export capabilities for selected administrative and academic data.

Import functionality should include:

* Data validation
* Permission checks
* Error reporting
* Duplicate detection
* Transaction safety
* Import summaries

### Guardian–Student Linking

Automatic linking between guardian accounts and students is intentionally deferred.

It should only be implemented after a secure and reliable identification and verification mechanism is approved.

---

# Development Principles

The project follows several backend development principles:

* Business logic should not be unnecessarily duplicated.
* Permissions must be enforced on the backend.
* Sensitive actions should be validated explicitly.
* Database constraints should protect important invariants where appropriate.
* Services should be used for important multi-step business operations.
* API responses should remain predictable and consistent.
* Breaking API changes should be coordinated with frontend and mobile teams.
* Production data must not be modified through unsafe development shortcuts.
* Security-sensitive information must never be committed to the repository.

---

# Project Status

The Asas School Backend is under active development and currently includes the main academic and administrative modules required for the initial school management platform.

Additional improvements will continue to be implemented incrementally based on project priorities and operational requirements.
