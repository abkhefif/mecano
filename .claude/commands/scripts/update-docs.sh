#!/bin/bash
# /update-docs - Update documentation based on project changes
# Usage: /update-docs
#
# This script automatically updates your documentation files to reflect
# changes in your command structure. It's designed to be easily customizable
# for your project's specific documentation needs.

# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================

# Which documentation files to update
DOCS_TO_UPDATE=("README.md" "CUSTOMIZING.md" "SKILLS.md")

# Auto-commit changes after updating (default: false for safety)
AUTO_COMMIT_DOCS=false

# Show detailed progress messages
VERBOSE=true

# ============================================
# CUSTOMIZATION GUIDE
# ============================================
# This script has several update functions you can enable/disable:
#
# README.md updates:
#   - update_command_count()     : Updates "X essential slash commands"
#   - update_chmod_paths()       : Fixes chmod paths for new structure
#   - update_command_table()     : Regenerates command table from .md files
#   - add_architecture_section() : Adds "How It Works" section
#
# CUSTOMIZING.md updates:
#   - update_script_paths()      : Updates script paths in examples
#   - add_structure_section()    : Adds dual-file architecture explanation
#
# SKILLS.md updates:
#   - add_clarification_note()   : Adds note about slash commands vs skills
#
# To disable a specific update, comment out the function call in the
# update_readme(), update_customizing(), or update_skills() functions below.
#
# To add your own updates, create a new function following the pattern
# and call it from the appropriate update_*() function.
# ============================================

set -e

echo "📚 Updating Documentation..."
echo ""

# ============================================
# INTERNAL FUNCTIONS - You probably don't need to modify these
# ============================================

# Collect command information from .md files
declare -A COMMANDS
collect_commands() {
    echo "Step 1/5: Analyzing command structure..."

    local md_count=0
    local script_count=0

    # Read all .md command files
    for cmd_file in .claude/commands/*.md; do
        if [ -f "$cmd_file" ]; then
            local cmd_name=$(basename "$cmd_file" .md)
            local description=$(grep "^description:" "$cmd_file" 2>/dev/null | sed 's/description: *//' || echo "No description")
            COMMANDS["$cmd_name"]="$description"
            md_count=$((md_count + 1)) || true
        fi
    done

    # Count scripts
    script_count=$(find .claude/commands/scripts -name "*.sh" -type f 2>/dev/null | wc -l) || script_count=0

    if [ "$VERBOSE" = true ]; then
        echo "  Found $md_count markdown command files"
        echo "  Found $script_count bash scripts"
    fi

    echo "✅ Structure analyzed"
    echo ""
}

# ============================================
# README.md UPDATE FUNCTIONS
# ============================================

# Main README.md update orchestrator
update_readme() {
    echo "Step 2/5: Updating README.md..."

    if [ ! -f "README.md" ]; then
        echo "⚠️  README.md not found, skipping..."
        echo ""
        return
    fi

    # Create backup
    cp README.md README.md.backup

    local updates=0

    # Update command count (e.g., "10 essential" → "12 essential")
    if grep -q "[0-9]* essential slash commands" README.md; then
        sed -i.tmp "s/[0-9]* essential slash commands/${#COMMANDS[@]} essential slash commands/g" README.md && rm -f README.md.tmp
        updates=$((updates + 1)) || true
        [ "$VERBOSE" = true ] && echo "  ✓ Updated command count to ${#COMMANDS[@]}"
    fi

    # Update chmod path for new structure
    if grep -q "chmod +x .claude/commands/\*\.sh" README.md; then
        sed -i.tmp 's|chmod +x .claude/commands/\*\.sh|chmod +x .claude/commands/scripts/*.sh|g' README.md && rm -f README.md.tmp
        updates=$((updates + 1)) || true
        [ "$VERBOSE" = true ] && echo "  ✓ Updated chmod path"
    fi

    # Regenerate command table from .md files
    update_command_table
    updates=$((updates + 1)) || true
    [ "$VERBOSE" = true ] && echo "  ✓ Updated command table"

    # Add architecture explanation if missing
    if ! grep -q "## How It Works" README.md; then
        add_architecture_section
        updates=$((updates + 1)) || true
        [ "$VERBOSE" = true ] && echo "  ✓ Added architecture section"
    fi

    echo "✅ README.md updated ($updates changes)"
    echo ""
}

# Update command table in README.md
update_command_table() {
    # Find the table start and end
    local start_line=$(grep -n "^| Command | Description |$" README.md | head -1 | cut -d: -f1)

    if [ -z "$start_line" ]; then
        return
    fi

    # Generate new table
    local temp_file=$(mktemp)

    # Copy everything before the table
    head -n $((start_line - 1)) README.md > "$temp_file"

    # Add table header
    echo "| Command | Description |" >> "$temp_file"
    echo "|---------|-------------|" >> "$temp_file"

    # Add commands in sorted order
    for cmd in $(echo "${!COMMANDS[@]}" | tr ' ' '\n' | sort); do
        # Special handling for pr-create-ga (add it at the end with note)
        if [ "$cmd" != "pr-create-ga" ]; then
            echo "| \`/$cmd\` | ${COMMANDS[$cmd]} |" >> "$temp_file"
        fi
    done

    # Add blank line
    echo "" >> "$temp_file"

    # Add advanced variant note if pr-create-ga exists
    if [ -n "${COMMANDS[pr-create-ga]}" ]; then
        echo "**Advanced variant:** \`/pr-create-ga\` - ${COMMANDS[pr-create-ga]}" >> "$temp_file"
        echo "" >> "$temp_file"
    fi

    # Find where to resume (skip old table and advanced variant line)
    local end_line=$(tail -n +$((start_line + 1)) README.md | grep -n "^## " | head -1 | cut -d: -f1)
    if [ -n "$end_line" ]; then
        tail -n +$((start_line + end_line)) README.md >> "$temp_file"
    else
        # If no next section found, just take rest of file after reasonable offset
        tail -n +$((start_line + 15)) README.md >> "$temp_file"
    fi

    # Replace original
    mv "$temp_file" README.md
}

# Add architecture section to README.md
add_architecture_section() {
    # Find insertion point (before "Documentation" section)
    local insert_line=$(grep -n "^## Documentation$" README.md | head -1 | cut -d: -f1)

    if [ -z "$insert_line" ]; then
        return
    fi

    local temp_file=$(mktemp)

    # Copy everything before insertion point
    head -n $((insert_line - 1)) README.md > "$temp_file"

    # Add new section
    cat >> "$temp_file" << 'EOF'
## How It Works

This repository uses a **dual-file architecture** for slash commands:

- **Markdown files** (`.claude/commands/*.md`) - Command definitions that Claude Code recognizes
- **Bash scripts** (`.claude/commands/scripts/*.sh`) - Implementation logic with your tested code

When you type `/test`, Claude reads `test.md` which instructs it to execute `scripts/test.sh`. This separation allows:

- ✅ **Claude Code compatibility** - Markdown files with YAML frontmatter are recognized as commands
- ✅ **Preserved logic** - Your bash scripts remain intact and testable
- ✅ **Easy customization** - Edit script configuration blocks without touching command definitions
- ✅ **Script reusability** - Scripts can call each other (e.g., `/commit` calls `/quality`)

EOF

    # Add rest of file
    tail -n +$insert_line README.md >> "$temp_file"

    # Replace original
    mv "$temp_file" README.md
}

# ============================================
# CUSTOMIZING.md UPDATE FUNCTIONS
# ============================================

# Main CUSTOMIZING.md update orchestrator
update_customizing() {
    echo "Step 3/5: Updating CUSTOMIZING.md..."

    if [ ! -f "CUSTOMIZING.md" ]; then
        echo "⚠️  CUSTOMIZING.md not found, skipping..."
        echo ""
        return
    fi

    # Create backup
    cp CUSTOMIZING.md CUSTOMIZING.md.backup

    local updates=0

    # Update script paths in examples (old structure → new structure)
    if grep -q '\.claude/commands/quality\.sh' CUSTOMIZING.md; then
        sed -i.tmp 's|\.claude/commands/quality\.sh|.claude/commands/scripts/quality.sh|g' CUSTOMIZING.md && rm -f CUSTOMIZING.md.tmp
        sed -i.tmp 's|\.claude/commands/test\.sh|.claude/commands/scripts/test.sh|g' CUSTOMIZING.md && rm -f CUSTOMIZING.md.tmp
        updates=$((updates + 1)) || true
        [ "$VERBOSE" = true ] && echo "  ✓ Updated script paths"
    fi

    # Add dual-file architecture explanation if missing
    if ! grep -q "## Understanding the Command Structure" CUSTOMIZING.md; then
        add_structure_section_to_customizing
        updates=$((updates + 1)) || true
        [ "$VERBOSE" = true ] && echo "  ✓ Added structure explanation"
    fi

    echo "✅ CUSTOMIZING.md updated ($updates changes)"
    echo ""
}

# Add structure explanation to CUSTOMIZING.md
add_structure_section_to_customizing() {
    # Insert after Table of Contents
    local insert_line=$(grep -n "^---$" CUSTOMIZING.md | head -2 | tail -1 | cut -d: -f1)

    if [ -z "$insert_line" ]; then
        return
    fi

    local temp_file=$(mktemp)

    # Copy everything before insertion point
    head -n $insert_line CUSTOMIZING.md > "$temp_file"

    # Add new section
    cat >> "$temp_file" << 'EOF'

## Understanding the Command Structure

This repository uses a **dual-file architecture**:

```
.claude/
└── commands/
    ├── test.md              ← Markdown wrapper (Claude Code recognizes this)
    ├── quality.md           ← Markdown wrapper
    ├── commit.md            ← Markdown wrapper
    └── scripts/
        ├── test.sh          ← Bash implementation (your logic here)
        ├── quality.sh       ← Bash implementation
        └── commit.sh        ← Bash implementation
```

### How It Works

1. **You type:** `/test`
2. **Claude reads:** `.claude/commands/test.md`
3. **Claude executes:** `bash .claude/commands/scripts/test.sh`

### Why This Structure?

- **Compatibility**: Claude Code requires `.md` files with YAML frontmatter
- **Separation of Concerns**: Command definition (what) vs implementation (how)
- **Testability**: You can run scripts directly: `bash .claude/commands/scripts/test.sh`
- **Maintainability**: Edit configuration blocks in scripts without touching `.md` files

### Customizing Commands

To customize a command's behavior, edit the bash script in `.claude/commands/scripts/`:

```bash
# Example: .claude/commands/scripts/test.sh
# ============================================
# CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================
COVERAGE_THRESHOLD=90  # Change this
TIMEOUT=600           # Or this
# ============================================
```

The markdown wrapper (`.claude/commands/test.md`) rarely needs changes unless you're modifying how arguments are passed.

---
EOF

    # Add rest of file
    tail -n +$((insert_line + 1)) CUSTOMIZING.md >> "$temp_file"

    # Replace original
    mv "$temp_file" CUSTOMIZING.md
}

# ============================================
# SKILLS.md UPDATE FUNCTIONS
# ============================================

# Main SKILLS.md update orchestrator
update_skills() {
    echo "Step 4/5: Analyzing SKILLS.md coverage..."

    if [ ! -f "SKILLS.md" ]; then
        echo "⚠️  SKILLS.md not found, skipping..."
        echo ""
        return
    fi

    # Create backup
    cp SKILLS.md SKILLS.md.backup

    local updates=0

    # Add clarification note at the top if not already present
    # Check if the note exists at the very beginning (line 1)
    local first_line=$(head -n 1 SKILLS.md)
    if [[ ! "$first_line" =~ "Note: These are slash commands" ]]; then
        local temp_file=$(mktemp)
        echo "> **Note:** These are slash commands (user-invoked via \`/command\`), not Claude Agent Skills (automatic). See [Claude Code documentation](https://code.claude.com/docs/en/skills) for the difference." > "$temp_file"
        echo "" >> "$temp_file"
        cat SKILLS.md >> "$temp_file"
        mv "$temp_file" SKILLS.md
        updates=$((updates + 1)) || true
        [ "$VERBOSE" = true ] && echo "  ✓ Added clarification note"
    else
        [ "$VERBOSE" = true ] && echo "  ℹ Clarification note already present"
    fi

    # Check which commands are missing documentation
    echo ""
    echo "  Checking documentation coverage..."
    local missing_commands=()

    for cmd in "${!COMMANDS[@]}"; do
        # Check if command has a dedicated section in SKILLS.md
        if ! grep -q "^## /$cmd" SKILLS.md; then
            missing_commands+=("$cmd")
        fi
    done

    if [ ${#missing_commands[@]} -gt 0 ]; then
        echo ""
        echo "  ⚠️  Commands missing detailed documentation in SKILLS.md:"
        for cmd in "${missing_commands[@]}"; do
            echo "     - /$cmd: ${COMMANDS[$cmd]}"
        done
        echo ""
        echo "  ℹ️  Claude will need to generate documentation for these commands."
        echo "     The bash script only handles mechanical updates (counts, paths, tables)."
        echo "     Content generation requires Claude's intelligence."
    else
        echo "  ✅ All commands are documented in SKILLS.md"
    fi

    echo ""
    echo "✅ SKILLS.md analysis complete ($updates mechanical updates)"
    echo ""
}

# ============================================
# SUMMARY AND REPORTING
# ============================================

# Generate summary of what was updated
generate_summary() {
    echo "Step 5/5: Generating summary..."
    echo ""

    echo "=========================================="
    echo ""
    echo "📋 Documentation Update Summary"
    echo ""

    echo "Command Structure:"
    echo "  .claude/commands/*.md      - Slash command definitions (${#COMMANDS[@]} commands)"
    echo "  .claude/commands/scripts/  - Bash script implementations"
    echo ""

    echo "Commands Available:"
    for cmd in $(echo "${!COMMANDS[@]}" | tr ' ' '\n' | sort); do
        echo "  /$cmd - ${COMMANDS[$cmd]}"
    done
    echo ""

    echo "Mechanical Updates Completed:"
    for doc in "${DOCS_TO_UPDATE[@]}"; do
        if [ -f "$doc.backup" ]; then
            echo "  ✅ $doc (backup: $doc.backup)"
        elif [ -f "$doc" ]; then
            echo "  ⚠️  $doc (no changes made)"
        else
            echo "  ❌ $doc (not found)"
        fi
    done
    echo ""

    # Check for missing documentation
    local missing_docs=()
    for cmd in "${!COMMANDS[@]}"; do
        if [ -f "SKILLS.md" ] && ! grep -q "^## /$cmd" SKILLS.md; then
            missing_docs+=("$cmd")
        fi
    done

    if [ ${#missing_docs[@]} -gt 0 ]; then
        echo "⚠️  CLAUDE ACTION REQUIRED:"
        echo ""
        echo "The following commands need detailed documentation in SKILLS.md:"
        for cmd in "${missing_docs[@]}"; do
            echo "  - /$cmd"
        done
        echo ""
        echo "This bash script can only do mechanical updates (counts, paths, tables)."
        echo "Claude needs to:"
        echo "  1. Read each command's .md and .sh files"
        echo "  2. Generate comprehensive documentation following SKILLS.md patterns"
        echo "  3. Add sections for missing commands"
        echo "  4. Update the Table of Contents"
        echo ""
    fi

    echo "Next Steps for Review:"
    echo "  1. Review mechanical updates:"
    echo "     git diff README.md"
    echo "     git diff CUSTOMIZING.md"
    echo "  2. If commands are missing from SKILLS.md, Claude will generate docs"
    echo "  3. Review all changes:"
    echo "     git diff SKILLS.md"
    echo "  4. Delete backups when satisfied: rm *.backup"
    if [ "$AUTO_COMMIT_DOCS" = false ]; then
        echo "  5. Commit changes: git add *.md && git commit -m 'docs: update documentation'"
    fi
    echo ""
}

# ============================================
# MAIN EXECUTION
# ============================================

# Run all update steps
collect_commands
update_readme
update_customizing
update_skills
generate_summary

# Optional: Auto-commit changes
if [ "$AUTO_COMMIT_DOCS" = true ]; then
    echo "Committing documentation updates..."
    if git add "${DOCS_TO_UPDATE[@]}" 2>/dev/null; then
        git commit -m "docs: update command structure documentation" || echo "Nothing to commit"
        echo "✅ Documentation committed"
    else
        echo "⚠️  Could not stage documentation files"
    fi
    echo ""
fi

echo "✅ Documentation update complete!"
exit 0

# ============================================
# HOW TO ADD YOUR OWN CUSTOM UPDATES
# ============================================
#
# 1. Create a new function following this pattern:
#
#    my_custom_update() {
#        if grep -q "old text" README.md; then
#            sed -i.tmp 's/old text/new text/g' README.md && rm -f README.md.tmp
#            [ "$VERBOSE" = true ] && echo "  ✓ Applied my custom update"
#        fi
#    }
#
# 2. Call your function from the appropriate update_*() function:
#
#    update_readme() {
#        ...
#        my_custom_update  # Add this line
#        ...
#    }
#
# 3. Test your changes:
#    bash .claude/commands/scripts/update-docs.sh
#
# 4. Common patterns:
#
#    # Check if text exists before updating (idempotent)
#    if ! grep -q "new text" file.md; then
#        # Add new text
#    fi
#
#    # Replace text
#    sed -i.tmp 's/old/new/g' file.md && rm -f file.md.tmp
#
#    # Insert section at specific location
#    local temp_file=$(mktemp)
#    head -n 10 file.md > "$temp_file"
#    echo "new content" >> "$temp_file"
#    tail -n +11 file.md >> "$temp_file"
#    mv "$temp_file" file.md
#
# ============================================
