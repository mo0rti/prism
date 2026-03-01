---
to: _manual
message: |
  Add this to shared/api-contracts/openapi.yml under the "paths:" section:

    /<%= h.changeCase.param(h.inflection.pluralize(entity)) %><%= path %>:
      <%= method.toLowerCase() %>:
        tags:
          - <%= h.changeCase.pascal(h.inflection.pluralize(entity)) %>
        summary: <%= description %>
        operationId: <%= h.changeCase.camel(method.toLowerCase() + '_' + h.inflection.pluralize(entity) + '_' + (path ? path.replace(/\//g, '_') : '')) %>
  <% if (method === 'GET') { %>
        parameters:
          - name: page
            in: query
            schema:
              type: integer
              default: 0
          - name: size
            in: query
            schema:
              type: integer
              default: 20
        responses:
          '200':
            description: Success
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/Paged<%= h.changeCase.pascal(entity) %>Response'
  <% } else if (method === 'POST') { %>
        requestBody:
          required: true
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/<%= h.changeCase.pascal(entity) %>Request'
        responses:
          '201':
            description: Created
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/<%= h.changeCase.pascal(entity) %>Response'
  <% } else if (method === 'PUT' || method === 'PATCH') { %>
        requestBody:
          required: true
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/<%= h.changeCase.pascal(entity) %>Request'
        responses:
          '200':
            description: Updated
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/<%= h.changeCase.pascal(entity) %>Response'
  <% } else if (method === 'DELETE') { %>
        responses:
          '204':
            description: Deleted
  <% } %>

  Then run: task generate-clients
---
