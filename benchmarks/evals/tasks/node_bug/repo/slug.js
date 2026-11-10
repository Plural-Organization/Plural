function slug(title) {
  return title.toLowerCase().replace(" ", "-");
}

module.exports = { slug };
