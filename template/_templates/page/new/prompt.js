module.exports = {
  prompt: ({ inquirer }) => {
    const questions = [
      {
        type: 'list',
        name: 'target',
        message: 'Which app?',
        choices: ['web-user-app', 'web-admin-portal'],
      },
      {
        type: 'input',
        name: 'route',
        message: 'Route path (e.g., "favorites", "settings/profile")',
        validate: (v) => v.length > 0 || 'Route path is required',
      },
      {
        type: 'input',
        name: 'title',
        message: 'Page title (e.g., "Favorites", "Profile Settings")',
        validate: (v) => v.length > 0 || 'Page title is required',
      },
      {
        type: 'confirm',
        name: 'protected',
        message: 'Requires authentication?',
        default: true,
      },
    ]
    return inquirer.prompt(questions)
  },
}
