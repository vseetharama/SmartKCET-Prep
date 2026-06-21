module.exports = {
  testEnvironment: 'jsdom',
  testMatch: ['**/*.test.js'],
  moduleFileExtensions: ['js'],
  collectCoverageFrom: [
    'frontend/js/**/*.js',
    '!frontend/js/**/*.test.js'
  ]
};
