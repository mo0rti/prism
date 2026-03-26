module.exports = {
  prompt: ({ inquirer }) => {
    const questions = [
      {
        type: 'list',
        name: 'platform',
        message: 'Platform',
        choices: ['mobile-android', 'mobile-ios'],
      },
      {
        type: 'input',
        name: 'name',
        message: 'Screen name (e.g., "Favorites", "Settings", "Profile")',
        validate: (v) => v.length > 0 || 'Screen name is required',
      },
      {
        type: 'input',
        name: 'feature',
        message: 'Feature folder (e.g., "favorites") — used for package/directory',
        validate: (v) => v.length > 0 || 'Feature folder is required',
      },
    ]
    return inquirer.prompt(questions)
  },
}
