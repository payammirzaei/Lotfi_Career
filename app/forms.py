"""
Form builder utilities and WPCF7 parser
"""
import re
import nh3
from markupsafe import Markup, escape
from flask import current_app

# HTML that form owners may use in templates. Everything else (script, style,
# iframe, on* handlers, javascript: URLs, ...) is stripped before rendering.
_ALLOWED_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'button', 'code', 'div', 'em', 'fieldset',
    'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'input', 'label',
    'legend', 'li', 'ol', 'optgroup', 'option', 'p', 'pre', 'section', 'select', 'small',
    'span', 'strong', 'sub', 'sup', 'table', 'tbody', 'td', 'textarea', 'tfoot', 'th',
    'thead', 'tr', 'u', 'ul',
}
_COMMON_ATTRS = {'class', 'id', 'dir', 'lang', 'title', 'style', 'role', 'aria-label', 'aria-describedby'}
_ALLOWED_ATTRS = {
    '*': _COMMON_ATTRS,
    'a': {'href', 'target'},
    'img': {'src', 'alt', 'width', 'height'},
    'form': {'method', 'action', 'enctype'},
    'input': {'type', 'name', 'value', 'placeholder', 'required', 'checked', 'min', 'max',
              'step', 'accept', 'maxlength', 'minlength', 'pattern', 'autocomplete', 'disabled', 'readonly'},
    'textarea': {'name', 'rows', 'cols', 'placeholder', 'required', 'maxlength', 'minlength'},
    'select': {'name', 'required', 'multiple'},
    'option': {'value', 'selected'},
    'optgroup': {'label'},
    'button': {'type', 'name', 'value'},
    'label': {'for'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan', 'scope'},
}


def sanitize_form_html(html):
    """Strip anything that could execute script from owner-supplied HTML."""
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes={'http', 'https', 'mailto', 'tel'},
        link_rel='noopener noreferrer',
        strip_comments=True,
    )


def _inject_csrf(html, token):
    """Add the CSRF hidden input to every <form> in the rendered HTML."""
    hidden = f'<input type="hidden" name="csrf_token" value="{escape(token)}">'
    return re.sub(r'(<form\b[^>]*>)', lambda m: m.group(1) + hidden, html, flags=re.IGNORECASE)


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


FIELD_PATTERN = re.compile(r'\[(\w+)(\*?)(?:\s+([^\]]*))?\]')
_NAMELESS_TYPES = {'submit'}


def _parse_tag(match):
    """Turn one [type* name attrs...] tag into a field definition.

    Shared by the parser (validation on submit) and the renderer so both see
    exactly the same field, attributes and options.
    """
    field_type = match.group(1)
    required = match.group(2) == '*'
    rest = (match.group(3) or '').strip()

    if field_type in _NAMELESS_TYPES or not rest or rest.startswith(('class=', '"')):
        field_name, attributes = field_type, rest      # e.g. [submit class="..." "Send"]
    else:
        parts = rest.split(None, 1)
        field_name, attributes = parts[0], (parts[1] if len(parts) > 1 else '')

    attrs = {}
    class_match = re.search(r'class="([^"]*)"', attributes)
    if class_match:
        attrs['class'] = class_match.group(1)
    else:
        class_parts = re.findall(r'class:(\S+)', attributes)
        if class_parts:
            attrs['class'] = ' '.join(class_parts)

    placeholder_match = re.search(r'placeholder\s+"([^"]*)"', attributes)
    if placeholder_match:
        attrs['placeholder'] = placeholder_match.group(1)

    for key in ('rows', 'min', 'max', 'step', 'default'):
        m = re.search(key + r':(\d+)', attributes)
        if m:
            attrs[key] = int(m.group(1))

    limit_match = re.search(r'limit:(\d+)(\w*)', attributes)
    if limit_match:
        attrs['limit'] = limit_match.group(1) + limit_match.group(2)
    filetypes_match = re.search(r'filetypes:(\S+)', attributes)
    if filetypes_match:
        attrs['filetypes'] = filetypes_match.group(1)
    for flag in ('use_label_element', 'include_blank'):
        if flag in attributes:
            attrs[flag] = True

    # Quoted values that are not class/placeholder: options, quiz Q|A, button text
    bare = re.sub(r'class="[^"]*"', ' ', attributes)
    bare = re.sub(r'placeholder\s+"[^"]*"', ' ', bare)
    options = re.findall(r'"([^"]*)"', bare)

    if field_type == 'quiz' and options:
        question, _, answer = options[0].partition('|')
        attrs['question'], attrs['answer'] = question.strip(), answer.strip()
    if field_type == 'submit' and options:
        attrs['button_text'] = options[-1]

    return {
        'type': field_type,
        'name': field_name,
        'required': required,
        'attributes': attrs,
        'options': [o for o in options if o.strip()] if field_type in ('select', 'radio', 'checkbox') else options,
    }


def parse_form_template(template):
    """Parse WPCF7-like form template and extract field definitions"""
    return [_parse_tag(m) for m in FIELD_PATTERN.finditer(template or '')]


def render_form_field(field_def, form_id):
    """Render a form field based on field definition"""
    field_type = field_def['type']
    field_name = field_def['name']
    required = field_def.get('required', False)
    attrs = field_def.get('attributes', {})

    classes = attrs.get('class', 'w-full rounded-lg border-gray-300 focus:border-indigo-500 focus:ring-indigo-500')
    required_attr = 'required' if required else ''
    required_mark = ' *' if required else ''

    placeholder_attr = f'placeholder="{attrs.get("placeholder", "")}"' if attrs.get('placeholder') else ''

    if field_type == 'text':
        return f'<input type="text" name="{field_name}" id="{field_name}" class="{classes}" {placeholder_attr} {required_attr} />'

    elif field_type == 'email':
        return f'<input type="email" name="{field_name}" id="{field_name}" class="{classes}" {placeholder_attr} {required_attr} />'

    elif field_type == 'tel':
        return f'<input type="tel" name="{field_name}" id="{field_name}" class="{classes}" {placeholder_attr} {required_attr} />'

    elif field_type == 'url':
        return f'<input type="url" name="{field_name}" id="{field_name}" class="{classes}" {placeholder_attr} {required_attr} />'

    elif field_type == 'number':
        min_attr = f'min="{attrs.get("min", "")}"' if attrs.get('min') is not None else ''
        max_attr = f'max="{attrs.get("max", "")}"' if attrs.get('max') is not None else ''
        step_attr = f'step="{attrs.get("step", "")}"' if attrs.get('step') is not None else ''
        return f'<input type="number" name="{field_name}" id="{field_name}" class="{classes}" {min_attr} {max_attr} {step_attr} {required_attr} />'

    elif field_type == 'date':
        return f'<input type="date" name="{field_name}" id="{field_name}" class="{classes}" {required_attr} />'

    elif field_type == 'textarea':
        rows = attrs.get('rows', 5)
        placeholder_attr = f'placeholder="{attrs.get("placeholder", "")}"' if attrs.get('placeholder') else ''
        return f'<textarea name="{field_name}" id="{field_name}" rows="{rows}" class="{classes}" {placeholder_attr} {required_attr}></textarea>'

    elif field_type == 'file':
        accept_attr = ''
        if attrs.get('filetypes'):
            filetypes = attrs['filetypes'].split('|')
            accept_attr = f'accept=".{",.".join(filetypes)}"'
        return f'<input type="file" name="{field_name}" id="{field_name}" class="{classes}" {accept_attr} {required_attr} />'

    elif field_type == 'select':
        # Extract options from template (simplified - would need more parsing)
        return f'<select name="{field_name}" id="{field_name}" class="{classes}" {required_attr}><option value="">Select an option</option></select>'

    elif field_type == 'radio':
        return f'<div class="space-y-2" data-field-name="{field_name}"></div>'

    elif field_type == 'checkbox':
        return f'<div class="space-y-2" data-field-name="{field_name}"></div>'

    elif field_type == 'acceptance':
        return f'<input type="checkbox" name="{field_name}" id="{field_name}" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" {required_attr} />'

    elif field_type == 'quiz':
        # Extract quiz question and answer
        return f'<input type="text" name="{field_name}" id="{field_name}" class="{classes}" {required_attr} placeholder="Enter answer" />'

    elif field_type == 'submit':
        button_text = attrs.get('text', 'Submit')
        return f'<button type="submit" class="{classes}">{button_text}</button>'

    return ''


def render_form_from_template(template, form_id, submit_url, csrf_token_value=None):
    """Render complete form HTML from WPCF7 template"""
    def replace(m):
        if m.group(1) not in KNOWN_FIELD_TYPES:
            return m.group(0)  # not a field tag (e.g. "[Optional]" in a label) - keep the text
        return render_form_field_with_options(_parse_tag(m), form_id)

    html = FIELD_PATTERN.sub(replace, template or '')

    # Wrap in form tag
    if '<form' not in html.lower():
        html = f'<form method="POST" action="{escape(submit_url)}" enctype="multipart/form-data" class="space-y-6">' + html + '</form>'

    html = sanitize_form_html(html)
    if csrf_token_value:
        html = _inject_csrf(html, csrf_token_value)
    return Markup(html)


def render_form_field_with_options(field_def, form_id):
    """Render form field with options support"""
    from flask import url_for

    field_type = field_def['type']
    field_name = field_def['name']
    required = field_def.get('required', False)
    attrs = field_def.get('attributes', {})
    options = field_def.get('options', [])

    classes = attrs.get('class', 'w-full rounded-lg border-gray-300 focus:border-indigo-500 focus:ring-indigo-500')
    required_attr = 'required' if required else ''

    if field_type == 'select':
        html = f'<select name="{field_name}" id="{field_name}" class="{classes}" {required_attr}>'
        if attrs.get('include_blank'):
            html += '<option value="">--</option>'
        for option in options:
            html += f'<option value="{option}">{option}</option>'
        html += '</select>'
        return html

    elif field_type == 'radio':
        html = '<div class="space-y-2">'
        default_index = attrs.get('default', None)
        for i, option in enumerate(options):
            option_id = f'{field_name}_{i}'
            checked = 'checked' if (default_index is not None and i == default_index - 1) else ''
            html += f'''
            <div class="flex items-center">
                <input type="radio" name="{field_name}" id="{option_id}" value="{option}" class="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300" {checked} {required_attr if i == 0 else ""} />
                <label for="{option_id}" class="ml-2 text-sm text-gray-700">{option}</label>
            </div>
            '''
        html += '</div>'
        return html

    elif field_type == 'checkbox':
        html = '<div class="space-y-2">'
        for i, option in enumerate(options):
            option_id = f'{field_name}_{i}'
            html += f'''
            <div class="flex items-center">
                <input type="checkbox" name="{field_name}" id="{option_id}" value="{option}" class="h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded" />
                <label for="{option_id}" class="ml-2 text-sm text-gray-700">{option}</label>
            </div>
            '''
        html += '</div>'
        return html

    elif field_type == 'quiz':
        question = attrs.get('question', '')
        return f'''
        <div>
            <p class="text-sm font-medium text-gray-700 mb-2">{question}</p>
            <input type="text" name="{field_name}" id="{field_name}" class="{classes}" {required_attr} />
        </div>
        '''

    elif field_type == 'submit':
        button_text = attrs.get('button_text') or 'Submit'
        return f'<button type="submit" class="{classes}">{button_text}</button>'

    # Fallback to basic render
    return render_form_field(field_def, form_id)



KNOWN_FIELD_TYPES = {'text', 'email', 'tel', 'url', 'number', 'date', 'textarea', 'select', 'radio',
                     'checkbox', 'file', 'acceptance', 'quiz', 'submit'}
_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')


def analyze_form_template(template):
    """Return (fields, warnings) to help authors spot mistakes before publishing."""
    fields = parse_form_template(template)
    warnings = []
    inputs = [f for f in fields if f['type'] != 'submit' and f['type'] in KNOWN_FIELD_TYPES]

    unknown = sorted({f['type'] for f in fields if f['type'] not in KNOWN_FIELD_TYPES})
    if unknown:
        warnings.append('Tip: ' + ', '.join(f'[{t}]' for t in unknown) +
                        ' is not a field type, so it is shown as plain text.')

    seen, dupes = set(), set()
    for f in inputs:
        if f['name'] in seen:
            dupes.add(f['name'])
        seen.add(f['name'])
    if dupes:
        warnings.append('Duplicate field name(s): ' + ', '.join(sorted(dupes)) +
                        ' - each field needs a unique name or answers will overwrite each other.')

    bad = sorted({f['name'] for f in inputs if f['type'] in KNOWN_FIELD_TYPES and not _NAME_RE.match(f['name'])})
    if bad:
        warnings.append('Field names should start with a letter and use only letters, numbers, - and _: ' +
                        ', '.join(bad))

    if not inputs:
        warnings.append('The form has no fields yet. Use "Add field" to insert one.')
    if inputs and not any(f['type'] == 'submit' for f in fields):
        warnings.append('There is no [submit] button - applicants will not be able to send the form.')
    if inputs and not any(f['type'] == 'email' for f in inputs):
        warnings.append('Tip: add an [email*] field so you can contact applicants.')
    return fields, warnings
