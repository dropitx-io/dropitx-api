#!/bin/bash

# Test script for DropItX CLI

set -e

CLI_PATH="$(cd "$(dirname "$0")" && pwd)"
CLI="node $CLI_PATH/bin/dropitx.js"

echo "🧪 Testing DropItX CLI"
echo "====================="
echo ""

# Test 1: Help command
echo "Test 1: Help command"
OUTPUT=$($CLI --help)
if echo "$OUTPUT" | grep -q "DropItX CLI"; then
  echo "✅ PASS: Help command works"
else
  echo "❌ FAIL: Help command failed"
  exit 1
fi
echo ""

# Test 2: Version command
echo "Test 2: Version command"
OUTPUT=$($CLI --version)
if echo "$OUTPUT" | grep -q "1.0.0"; then
  echo "✅ PASS: Version command works"
else
  echo "❌ FAIL: Version command failed"
  exit 1
fi
echo ""

# Test 3: Login help
echo "Test 3: Login help"
OUTPUT=$($CLI login --help)
if echo "$OUTPUT" | grep -q "Authenticate with DropItX API key"; then
  echo "✅ PASS: Login help works"
else
  echo "❌ FAIL: Login help failed"
  exit 1
fi
echo ""

# Test 4: Upload help
echo "Test 4: Upload help"
OUTPUT=$($CLI upload --help)
if echo "$OUTPUT" | grep -q "Upload a file"; then
  echo "✅ PASS: Upload help works"
else
  echo "❌ FAIL: Upload help failed"
  exit 1
fi
echo ""

# Test 5: Download help
echo "Test 5: Download help"
OUTPUT=$($CLI download --help)
if echo "$OUTPUT" | grep -q "Download a shared file"; then
  echo "✅ PASS: Download help works"
else
  echo "❌ FAIL: Download help failed"
  exit 1
fi
echo ""

# Test 6: List help
echo "Test 6: List help"
OUTPUT=$($CLI list --help)
if echo "$OUTPUT" | grep -q "List your shared files"; then
  echo "✅ PASS: List help works"
else
  echo "❌ FAIL: List help failed"
  exit 1
fi
echo ""

# Test 7: Delete help
echo "Test 7: Delete help"
OUTPUT=$($CLI delete --help)
if echo "$OUTPUT" | grep -q "Delete a shared file"; then
  echo "✅ PASS: Delete help works"
else
  echo "❌ FAIL: Delete help failed"
  exit 1
fi
echo ""

echo "✅ All tests passed!"
echo ""
echo "To test with actual API:"
echo "  1. Run: dropitx login"
echo "  2. Run: dropitx upload test.txt"
echo "  3. Run: dropitx list"
