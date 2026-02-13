#!/bin/bash
# /scaffold - Generate boilerplate code
# Usage: /scaffold <type> <name>
# Examples: /scaffold component Button
#           /scaffold api users
#           /scaffold test utils

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
COMPONENT_DIR="src/components"  # React/Vue component directory
API_DIR="src/api"               # API endpoint directory
TEST_DIR="src/__tests__"        # Test file directory
UTIL_DIR="src/utils"            # Utility file directory
USE_TYPESCRIPT=true             # Generate .ts/.tsx instead of .js/.jsx
# ============================================

set -e

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "❌ Usage: /scaffold <type> <name>"
    echo ""
    echo "Available types:"
    echo "  component  - React/Vue component with test"
    echo "  api        - API endpoint handler"
    echo "  test       - Test file"
    echo "  util       - Utility function"
    exit 1
fi

TYPE="$1"
NAME="$2"

# Determine file extensions
if [ "$USE_TYPESCRIPT" = true ]; then
    EXT="ts"
    COMP_EXT="tsx"
else
    EXT="js"
    COMP_EXT="jsx"
fi

echo "🏗️  Scaffolding $TYPE: $NAME"
echo ""

# Component scaffold
if [ "$TYPE" = "component" ]; then
    COMPONENT_FILE="$COMPONENT_DIR/$NAME.$COMP_EXT"
    TEST_FILE="$COMPONENT_DIR/$NAME.test.$COMP_EXT"

    echo "Creating React component..."
    echo "  Component: $COMPONENT_FILE"
    echo "  Test: $TEST_FILE"
    echo ""

    # Create directory if it doesn't exist
    mkdir -p "$COMPONENT_DIR"

    # Generate component file
    cat > "$COMPONENT_FILE" <<EOF
import React from 'react';

interface ${NAME}Props {
  // Add your props here
}

export const $NAME: React.FC<${NAME}Props> = (props) => {
  return (
    <div className="$NAME">
      {/* Component content */}
    </div>
  );
};
EOF

    # Generate test file
    cat > "$TEST_FILE" <<EOF
import { render, screen } from '@testing-library/react';
import { $NAME } from './$NAME';

describe('$NAME', () => {
  it('renders without crashing', () => {
    render(<$NAME />);
  });

  // Add more tests here
});
EOF

    echo "✅ Component scaffolded!"
    echo ""
    echo "Files created:"
    echo "  - $COMPONENT_FILE"
    echo "  - $TEST_FILE"

# API endpoint scaffold
elif [ "$TYPE" = "api" ]; then
    API_FILE="$API_DIR/$NAME.$EXT"

    echo "Creating API endpoint..."
    echo "  Endpoint: $API_FILE"
    echo ""

    mkdir -p "$API_DIR"

    cat > "$API_FILE" <<EOF
/**
 * API handler for $NAME
 */

export async function get$NAME(req, res) {
  try {
    // GET handler logic
    res.status(200).json({ message: 'Success' });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}

export async function post$NAME(req, res) {
  try {
    // POST handler logic
    const data = req.body;
    res.status(201).json({ message: 'Created', data });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}

export async function update$NAME(req, res) {
  try {
    // PUT/PATCH handler logic
    const data = req.body;
    res.status(200).json({ message: 'Updated', data });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}

export async function delete$NAME(req, res) {
  try {
    // DELETE handler logic
    res.status(204).send();
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}
EOF

    echo "✅ API endpoint scaffolded!"
    echo ""
    echo "File created:"
    echo "  - $API_FILE"

# Test file scaffold
elif [ "$TYPE" = "test" ]; then
    TEST_FILE="$TEST_DIR/$NAME.test.$EXT"

    echo "Creating test file..."
    echo "  Test: $TEST_FILE"
    echo ""

    mkdir -p "$TEST_DIR"

    cat > "$TEST_FILE" <<EOF
import { $NAME } from '../$NAME';

describe('$NAME', () => {
  it('should work correctly', () => {
    // Add your test here
    expect(true).toBe(true);
  });

  // Add more test cases
});
EOF

    echo "✅ Test file scaffolded!"
    echo ""
    echo "File created:"
    echo "  - $TEST_FILE"

# Utility scaffold
elif [ "$TYPE" = "util" ]; then
    UTIL_FILE="$UTIL_DIR/$NAME.$EXT"
    TEST_FILE="$UTIL_DIR/$NAME.test.$EXT"

    echo "Creating utility function..."
    echo "  Util: $UTIL_FILE"
    echo "  Test: $TEST_FILE"
    echo ""

    mkdir -p "$UTIL_DIR"

    cat > "$UTIL_FILE" <<EOF
/**
 * $NAME utility function
 */

export function $NAME() {
  // Implementation here
}
EOF

    cat > "$TEST_FILE" <<EOF
import { $NAME } from './$NAME';

describe('$NAME', () => {
  it('should work correctly', () => {
    // Add your test here
  });
});
EOF

    echo "✅ Utility scaffolded!"
    echo ""
    echo "Files created:"
    echo "  - $UTIL_FILE"
    echo "  - $TEST_FILE"

else
    echo "❌ Unknown type: $TYPE"
    echo ""
    echo "Available types: component, api, test, util"
    exit 1
fi

echo ""
echo "✅ Scaffolding complete!"
