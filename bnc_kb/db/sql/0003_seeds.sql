INSERT INTO spec_dimension (code, label) VALUES
    ('context-and-requirements', 'Context and Requirements'),
    ('quality-attributes', 'Quality Attributes'),
    ('constraints', 'Constraints'),
    ('architecture-diagrams', 'Architecture Diagrams'),
    ('infrastructure-costs', 'Infrastructure Costs'),
    ('architectural-decisions', 'Architectural Decisions'),
    ('risks-and-technical-debts', 'Risks and Technical Debts'),
    ('processes', 'Processes'),
    ('solution-requirements', 'Solution Requirements'),
    ('data-requirements', 'Data Requirements'),
    ('business-rules', 'Business Rules')
ON CONFLICT (code) DO NOTHING;

INSERT INTO link_type (code, label) VALUES
    ('belongs_to', 'Belongs To'),
    ('derives_from', 'Derives From'),
    ('supersedes', 'Supersedes'),
    ('realizes', 'Realizes'),
    ('traces_to', 'Traces To'),
    ('depends_on', 'Depends On')
ON CONFLICT (code) DO NOTHING;
