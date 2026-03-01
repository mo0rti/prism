module.exports = {
  prompt: ({ inquirer }) => {
    const questions = [
      {
        type: 'input',
        name: 'name',
        message: 'Feature name (e.g., "restaurant-listings")',
        validate: (v) => v.length > 0 || 'Feature name is required',
      },
      {
        type: 'input',
        name: 'description',
        message: 'Brief description of the feature',
        validate: (v) => v.length > 0 || 'Description is required',
      },
      {
        type: 'input',
        name: 'entity',
        message: 'Primary entity name (e.g., "Restaurant") — leave empty to skip',
        default: '',
      },
    ]
    return inquirer.prompt(questions)
  },
}
