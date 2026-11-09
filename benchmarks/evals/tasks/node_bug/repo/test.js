const assert = require("node:assert");
const { slug } = require("./slug");

assert.equal(slug("Hello World"), "hello-world");
assert.equal(slug("  Many   Spaces here "), "many-spaces-here");
assert.equal(slug("Caffè & Crème!"), "caffe-creme");
