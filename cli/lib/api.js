const fetch = require('node-fetch');
const FormData = require('form-data');
const fs = require('fs');
const path = require('path');
const { getApiUrl, getApiKey } = require('./config');

async function uploadFile(filePath, options = {}) {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  
  const form = new FormData();
  const fileName = path.basename(filePath);
  const fileStream = fs.createReadStream(filePath);
  
  form.append('file', fileStream, fileName);
  
  if (options.burnAfterReading) {
    form.append('burn_after_reading', 'true');
  }
  
  if (options.expiresIn) {
    form.append('expires_in', options.expiresIn);
  }
  
  if (options.maxDownloads) {
    form.append('max_downloads', options.maxDownloads.toString());
  }
  
  const headers = {
    ...form.getHeaders(),
    'Authorization': `Bearer ${apiKey}`,
  };
  
  const response = await fetch(`${apiUrl}/api/upload`, {
    method: 'POST',
    headers,
    body: form,
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Upload failed');
  }
  
  return response.json();
}

async function uploadFromStdin(options = {}) {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  
  // Read from stdin
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const content = Buffer.concat(chunks);
  
  const form = new FormData();
  form.append('file', content, {
    filename: 'stdin.txt',
    contentType: 'text/plain',
  });
  
  if (options.burnAfterReading) {
    form.append('burn_after_reading', 'true');
  }
  
  if (options.expiresIn) {
    form.append('expires_in', options.expiresIn);
  }
  
  const headers = {
    ...form.getHeaders(),
    'Authorization': `Bearer ${apiKey}`,
  };
  
  const response = await fetch(`${apiUrl}/api/upload`, {
    method: 'POST',
    headers,
    body: form,
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Upload failed');
  }
  
  return response.json();
}

async function downloadFile(slug, outputPath) {
  const apiUrl = getApiUrl();
  
  const response = await fetch(`${apiUrl}/api/shares/${slug}`);
  
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('File not found');
    }
    const error = await response.json();
    throw new Error(error.detail || 'Download failed');
  }
  
  const data = await response.json();
  
  // Get the actual file URL
  const fileUrl = data.url;
  
  const fileResponse = await fetch(fileUrl);
  if (!fileResponse.ok) {
    throw new Error('Failed to download file content');
  }
  
  const buffer = await fileResponse.buffer();
  const fileName = data.filename || slug;
  const finalPath = outputPath || fileName;
  
  fs.writeFileSync(finalPath, buffer);
  return { path: finalPath, filename: fileName };
}

async function listDocuments(page = 1, limit = 20) {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  
  const response = await fetch(`${apiUrl}/api/v1/documents?page=${page}&limit=${limit}`, {
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to list documents');
  }
  
  return response.json();
}

async function deleteDocument(slug) {
  const apiUrl = getApiUrl();
  const apiKey = getApiKey();
  
  const response = await fetch(`${apiUrl}/api/v1/documents/${slug}`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
  });
  
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Document not found');
    }
    const error = await response.json();
    throw new Error(error.detail || 'Delete failed');
  }
  
  return true;
}

module.exports = {
  uploadFile,
  uploadFromStdin,
  downloadFile,
  listDocuments,
  deleteDocument,
};
