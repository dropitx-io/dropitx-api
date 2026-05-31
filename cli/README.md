# DropItX CLI

Share files from terminal with DropItX.

## Installation

```bash
npm install -g dropitx-cli
```

Or install from source:

```bash
git clone https://github.com/phuongddx/dropitx-api.git
cd dropitx-api/cli
npm install
npm link
```

## Quick Start

1. Login with your API key:
```bash
dropitx login
```

2. Upload a file:
```bash
dropitx upload myfile.txt
```

3. Download a shared file:
```bash
dropitx download https://dropitx.com/s/abc123
```

## Commands

### `dropitx login`
Authenticate with your DropItX API key.

```bash
dropitx login
dropitx login -k YOUR_API_KEY
dropitx login -u https://custom-api-url.com
```

### `dropitx upload [file]`
Upload a file and get a share URL.

```bash
# Basic upload
dropitx upload myfile.txt

# Upload with options
dropitx upload --burn myfile.txt          # Burn after reading
dropitx upload --expires 7d myfile.txt    # Expires in 7 days
dropitx upload --max-downloads 5 myfile.txt  # Max 5 downloads
dropitx upload --json myfile.txt          # Output as JSON

# Pipe support
cat myfile.txt | dropitx upload
echo "Hello" | dropitx upload
```

### `dropitx download <url>`
Download a shared file.

```bash
# Download from URL
dropitx download https://dropitx.com/s/abc123

# Download with custom output path
dropitx download https://dropitx.com/s/abc123 -o output.txt
```

### `dropitx list`
List your shared files.

```bash
# List all documents
dropitx list

# Pagination
dropitx list --page 2 --limit 10

# JSON output
dropitx list --json
```

### `dropitx delete <url>`
Delete a shared file.

```bash
# Delete with confirmation
dropitx delete https://dropitx.com/s/abc123

# Force delete (skip confirmation)
dropitx delete --force https://dropitx.com/s/abc123
```

## Configuration

Configuration is stored in `~/.config/dropitx/config.json`.

```json
{
  "apiUrl": "https://dropitx-api.onrender.com",
  "apiKey": "your-api-key"
}
```

## Environment Variables

- `DROPITX_API_URL` - Override API URL
- `DROPITX_API_KEY` - Override API key

## Examples

### Upload with burn after reading
```bash
dropitx upload --burn secret.txt
# ⚠ Burn after reading: file will be deleted after first download
```

### Upload with expiration
```bash
dropitx upload --expires 24h myfile.txt
# File expires in 24 hours
```

### Pipe from other commands
```bash
# Upload output of a command
ls -la | dropitx upload

# Upload from curl
curl -s https://api.example.com/data | dropitx upload
```

### Batch operations
```bash
# List all your files
dropitx list --json | jq '.[].slug'

# Delete multiple files
for url in $(dropitx list --json | jq -r '.[].slug'); do
  dropitx delete --force "$url"
done
```

## API Key

Get your API key from the DropItX dashboard:
1. Go to https://dropitx.com
2. Login to your account
3. Go to Settings > API Keys
4. Create a new API key

## Development

```bash
# Clone the repo
git clone https://github.com/phuongddx/dropitx-api.git
cd dropitx-api/cli

# Install dependencies
npm install

# Link for local development
npm link

# Run tests
npm test
```

## License

MIT
