# Certificate API

A RESTful API service built in Go for managing X.509 certificates. Upload root certificates and retrieve detailed information about them.

## Features

- Upload X.509 certificates in PEM format
- Retrieve detailed certificate information
- List all uploaded certificates
- Delete certificates
- In-memory storage for certificates
- Comprehensive certificate parsing (subject, issuer, validity, key usage, etc.)

## API Endpoints

### 1. Upload Certificate
**POST** `/api/v1/certificates`

Upload a PEM-encoded X.509 certificate.

**Request Body:**
```json
{
  "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
}
```

**Response (201 Created):**
```json
{
  "id": "abc123...",
  "subject": "CN=Example Root CA,O=Example Inc,C=US",
  "issuer": "CN=Example Root CA,O=Example Inc,C=US",
  "serial_number": "123456789",
  "not_before": "2024-01-01T00:00:00Z",
  "not_after": "2034-01-01T00:00:00Z",
  "signature_algorithm": "SHA256-RSA",
  "public_key_algorithm": "RSA",
  "key_usage": ["CertSign", "CRLSign"],
  "is_ca": true,
  "version": 3,
  "dns_names": [],
  "email_addresses": [],
  "ip_addresses": [],
  "uploaded_at": "2024-11-14T12:00:00Z"
}
```

### 2. Get Certificate Details
**GET** `/api/v1/certificates/{id}`

Retrieve details of a specific certificate by its ID.

**Response (200 OK):**
```json
{
  "id": "abc123...",
  "subject": "CN=Example Root CA,O=Example Inc,C=US",
  ...
}
```

### 3. List All Certificates
**GET** `/api/v1/certificates`

Retrieve a list of all uploaded certificates.

**Response (200 OK):**
```json
[
  {
    "id": "abc123...",
    "subject": "CN=Example Root CA,O=Example Inc,C=US",
    ...
  }
]
```

### 4. Delete Certificate
**DELETE** `/api/v1/certificates/{id}`

Delete a certificate by its ID.

**Response (200 OK):**
```json
{
  "message": "Certificate deleted successfully"
}
```

### 5. Health Check
**GET** `/health`

Check if the API is running.

**Response (200 OK):**
```json
{
  "status": "healthy"
}
```

## Getting Started

### Prerequisites

- Go 1.21 or higher

### Installation

1. Clone the repository:
```bash
git clone https://github.com/Ashmeet-21/Ash.git
cd Ash
```

2. Install dependencies:
```bash
go mod download
```

3. Run the server:
```bash
go run main.go
```

The server will start on port 8080 by default. You can change this by setting the `PORT` environment variable:
```bash
PORT=3000 go run main.go
```

### Building

Build the binary:
```bash
go build -o cert-api
./cert-api
```

## Usage Examples

### Using curl

1. **Upload a certificate:**
```bash
curl -X POST http://localhost:8080/api/v1/certificates \
  -H "Content-Type: application/json" \
  -d '{
    "certificate": "-----BEGIN CERTIFICATE-----\nMIIDXTCCAkWgAwIBAgIJAKL0UG+mRKSzMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV\n...\n-----END CERTIFICATE-----"
  }'
```

2. **List all certificates:**
```bash
curl http://localhost:8080/api/v1/certificates
```

3. **Get certificate details:**
```bash
curl http://localhost:8080/api/v1/certificates/{certificate-id}
```

4. **Delete a certificate:**
```bash
curl -X DELETE http://localhost:8080/api/v1/certificates/{certificate-id}
```

### Generating a Test Certificate

You can generate a self-signed root certificate for testing:

```bash
# Generate private key
openssl genrsa -out rootCA.key 2048

# Generate root certificate
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 3650 \
  -out rootCA.pem -subj "/C=US/ST=State/L=City/O=Organization/CN=Test Root CA"

# View the certificate
cat rootCA.pem
```

## Project Structure

```
.
├── main.go              # Application entry point
├── handlers/
│   └── certificate.go   # HTTP handlers for certificate endpoints
├── models/
│   └── certificate.go   # Data models
├── storage/
│   └── memory.go        # In-memory storage implementation
├── go.mod              # Go module dependencies
└── README.md           # This file
```

## Certificate Information Extracted

The API extracts and returns the following information from uploaded certificates:

- **Basic Information:** Subject, Issuer, Serial Number
- **Validity:** Not Before, Not After dates
- **Algorithms:** Signature Algorithm, Public Key Algorithm
- **Extensions:** Key Usage, Extended Key Usage
- **Attributes:** CA status, Version
- **Subject Alternative Names:** DNS names, Email addresses, IP addresses
- **Metadata:** Upload timestamp, Unique certificate ID (SHA-256 hash)

## Error Handling

The API returns appropriate HTTP status codes:

- `200 OK` - Successful operation
- `201 Created` - Certificate uploaded successfully
- `400 Bad Request` - Invalid request or certificate format
- `404 Not Found` - Certificate not found
- `500 Internal Server Error` - Server error

Error responses include a descriptive message:
```json
{
  "error": "Description of the error"
}
```

## License

MIT
