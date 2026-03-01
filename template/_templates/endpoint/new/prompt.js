module.exports = {
  prompt: ({ inquirer }) => {
    const questions = [
      {
        type: 'input',
        name: 'feature',
        message: 'Feature module name (e.g., "restaurant-listings")',
        validate: (v) => v.length > 0 || 'Feature name is required',
      },
      {
        type: 'input',
        name: 'entity',
        message: 'Entity name (e.g., "Restaurant")',
        validate: (v) => v.length > 0 || 'Entity name is required',
      },
      {
        type: 'list',
        name: 'method',
        message: 'HTTP method',
        choices: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
      },
      {
        type: 'input',
        name: 'path',
        message: 'Endpoint path (e.g., "/nearby" for GET /restaurants/nearby)',
        default: '',
      },
      {
        type: 'input',
        name: 'description',
        message: 'Endpoint description',
        validate: (v) => v.length > 0 || 'Description is required',
      },
    ]
    return inquirer.prompt(questions)
  },
}
